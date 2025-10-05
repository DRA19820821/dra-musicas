"""
FastAPI application for batch music generation using the Suno API stub.

This API exposes endpoints to upload batches of JSON prompt files,
choose generation parameters, and process them asynchronously. It
maintains state in a database via SQLAlchemy and persists generated
audio files to disk. A lightweight stub of the Suno API is used
instead of the real service to facilitate development and testing.

To run this application locally, install the dependencies listed in
``requirements.txt`` and start the server with:

    uvicorn app.main:app --reload

When using Docker Compose, the service will be exposed on port 8000.
"""

import asyncio
import datetime
import json
import logging
from pathlib import Path
from typing import List

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, BackgroundTasks
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from . import database, models, schemas, suno_client_stub


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Suno Batch Music Processor")

# Mount static frontend at root. This allows serving the simple
# HTML/JS application when accessed via a browser. The HTML file is
# located two directories up in the ``frontend`` folder relative to
# this file.
from fastapi.staticfiles import StaticFiles  # noqa: E402
frontend_dir = Path(__file__).resolve().parents[2] / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")


def get_db():
    """Yield a database session for dependency injection."""
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.on_event("startup")
async def startup_event() -> None:
    """Initialize the database on startup."""
    database.init_db()
    logger.info("Application startup complete.")


@app.get("/models", summary="List available Suno models")
async def list_models() -> dict:
    """Return a list of available model identifiers.

    In a real deployment this would query the `get_limit` endpoint of the
    Suno wrapper to determine which models are enabled for the user.
    Here we return a static list based on the specification.
    """
    return {"models": ["v4.5", "v5"]}


@app.post("/lotes", response_model=schemas.Lote)
async def create_lote(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(..., description="One or more JSON files"),
    modelo: str = "v4.5",
    prefer_wav: bool = True,
    allow_mp3_to_wav: bool = True,
    duracao_alvo: float = 360.0,
    extend_enabled: bool = True,
    extends_max: int = 2,
    concurrency: int = 2,
    retries: int = 3,
    timeout: float = 480.0,
    db: Session = Depends(get_db),
) -> schemas.Lote:
    """Create a new batch (lote) and schedule processing of each track.

    Accepts multiple JSON files uploaded via multipart/form-data. Each file
    must contain a JSON object with the keys ``letra`` and ``estilo``.
    Additional keys are preserved as metadata. The first line of the
    ``letra`` field is used as the track title.

    Parameters affecting generation (model, concurrency, retries, etc.)
    are attached to the batch and propagated to each track during
    processing.
    """
    if concurrency < 1 or concurrency > 4:
        raise HTTPException(status_code=400, detail="Concurrency must be between 1 and 4")

    lote = models.Lote(
        parametros={
            "modelo": modelo,
            "prefer_wav": prefer_wav,
            "allow_mp3_to_wav": allow_mp3_to_wav,
            "duracao_alvo": duracao_alvo,
            "extend_enabled": extend_enabled,
            "extends_max": extends_max,
            "concurrency": concurrency,
            "retries": retries,
            "timeout": timeout,
        },
        total_arquivos=len(files),
    )
    db.add(lote)
    db.commit()
    db.refresh(lote)

    faixa_ids = []
    for file in files:
        # Read contents
        contents = await file.read()
        try:
            data = json.loads(contents.decode("utf-8"))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"File {file.filename} is not valid JSON: {exc}")

        letra = data.get("letra")
        estilo = data.get("estilo")
        if not letra or not estilo:
            raise HTTPException(status_code=400, detail=f"File {file.filename} must contain 'letra' and 'estilo'")

        title_line = letra.strip().split("\n")[0]
        faixa = models.Faixa(
            lote_id=lote.id,
            titulo=title_line,
            estilo=estilo,
            modelo=modelo,
            duracao_alvo=duracao_alvo,
            metadata={k: v for k, v in data.items() if k not in {"letra", "estilo"}},
        )
        db.add(faixa)
        db.commit()
        db.refresh(faixa)
        faixa_ids.append(faixa.id)

    # schedule background processing of all tracks
    background_tasks.add_task(
        process_lote, lote.id, modelo, prefer_wav, allow_mp3_to_wav, duracao_alvo,
        extend_enabled, extends_max, concurrency, retries, timeout
    )

    # Load faixas for response
    lote = db.query(models.Lote).filter(models.Lote.id == lote.id).first()
    return lote


async def process_lote(
    lote_id: int,
    modelo: str,
    prefer_wav: bool,
    allow_mp3_to_wav: bool,
    duracao_alvo: float,
    extend_enabled: bool,
    extends_max: int,
    concurrency: int,
    retries: int,
    timeout: float,
) -> None:
    """Process all tracks in a batch with concurrency control."""
    sem = asyncio.Semaphore(concurrency)
    tasks = []
    async with database.engine.begin() as conn:
        pass  # placeholder to ensure engine is initialised
    # Use a separate session per task to avoid thread issues
    db = database.SessionLocal()
    lote = db.query(models.Lote).filter(models.Lote.id == lote_id).first()
    # Create tasks for each faixa
    for faixa in lote.faixas:
        tasks.append(
            asyncio.create_task(
                process_faixa(
                    faixa.id,
                    modelo,
                    prefer_wav,
                    allow_mp3_to_wav,
                    duracao_alvo,
                    extend_enabled,
                    extends_max,
                    retries,
                    timeout,
                    sem,
                )
            )
        )
    # Wait for all tasks
    await asyncio.gather(*tasks)
    db.close()


async def process_faixa(
    faixa_id: int,
    modelo: str,
    prefer_wav: bool,
    allow_mp3_to_wav: bool,
    duracao_alvo: float,
    extend_enabled: bool,
    extends_max: int,
    retries: int,
    timeout: float,
    sem: asyncio.Semaphore,
) -> None:
    """Process a single track: generate and optionally extend the audio."""
    async with sem:
        db = database.SessionLocal()
        faixa = db.query(models.Faixa).filter(models.Faixa.id == faixa_id).first()
        if not faixa:
            db.close()
            return
        faixa.tempo_submissao = datetime.datetime.utcnow()
        faixa.status = models.StatusEnum.GERANDO
        db.commit()
        db.refresh(faixa)
        try:
            # Attempt generation with retries
            attempts = 0
            while attempts <= retries:
                attempts += 1
                faixa.tentativas = attempts
                # Perform generation
                gen_id, urls, wav_native = await suno_client_stub.custom_generate(
                    faixa.titulo,
                    faixa.estilo,
                    faixa.metadata.get("letra", faixa.titulo),
                    modelo,
                    duracao_alvo,
                    prefer_wav,
                    allow_mp3_to_wav,
                )
                faixa.ids_suno = {"initial": gen_id}
                faixa.urls = urls
                faixa.wav_nativo = wav_native
                faixa.caminho_arquivo = urls["audio_url"]
                faixa.tempo_geracao = datetime.datetime.utcnow()
                # Determine duration of generated file
                # For stub we can't easily compute length; assume file name has unknown duration
                # We'll treat file length by dividing size
                file_path = Path(faixa.caminho_arquivo)
                if file_path.exists():
                    # Estimate duration from file size: sample_rate*2 bytes
                    file_size = file_path.stat().st_size
                    duration_est = file_size / (44100 * 2)  # approximate for mono 16‑bit
                    faixa.duracao_final = duration_est
                else:
                    faixa.duracao_final = None
                db.commit()
                if faixa.duracao_final and faixa.duracao_final >= duracao_alvo:
                    faixa.status = models.StatusEnum.FINALIZADA
                    db.commit()
                    break
                # If shorter and extension enabled
                if extend_enabled and attempts <= extends_max:
                    faixa.status = models.StatusEnum.ESTENDENDO
                    db.commit()
                    # Determine how much to extend: 60 seconds each call
                    extend_seconds = 60.0
                    ext_id, ext_urls, ext_wav = await suno_client_stub.extend_audio(
                        gen_id, extend_seconds, prefer_wav
                    )
                    # Update fields
                    faixa.extends_usados += 1
                    # Append audio file path to existing path (concatenate not physically, but record list)
                    faixa.ids_suno[f"extend_{faixa.extends_usados}"] = ext_id
                    # Append new file path
                    # In a real scenario we would download and append to previous audio.
                    # Here we simply note additional file and update duration estimate.
                    # Append durations
                    old_dur = faixa.duracao_final or 0
                    # Estimate extend duration from file size
                    file_path_ext = Path(ext_urls["audio_url"])
                    if file_path_ext.exists():
                        ext_file_size = file_path_ext.stat().st_size
                        ext_duration = ext_file_size / (44100 * 2)
                    else:
                        ext_duration = extend_seconds
                    faixa.duracao_final = old_dur + ext_duration
                    # update caminho_arquivo to last extension (for download). In production we would
                    # stitch files, but stub returns separate file.
                    faixa.caminho_arquivo = ext_urls["audio_url"]
                    db.commit()
                    # Check if reached target
                    if faixa.duracao_final >= duracao_alvo:
                        faixa.status = models.StatusEnum.FINALIZADA
                        db.commit()
                        break
                    else:
                        # continue loop for next extend
                        continue
                else:
                    # either extension disabled or reached max
                    faixa.status = models.StatusEnum.FINALIZADA
                    db.commit()
                    break
            else:
                # Exceeded retries
                faixa.status = models.StatusEnum.ERRO
                db.commit()
        except Exception as exc:
            logger.exception("Error processing faixa %s: %s", faixa.id, exc)
            faixa.status = models.StatusEnum.ERRO
            faixa.erros = {"detail": str(exc)}
            db.commit()
        finally:
            faixa.tempo_download = datetime.datetime.utcnow()
            db.commit()
            db.close()


@app.get("/lotes/{lote_id}", response_model=schemas.Lote)
async def get_lote(lote_id: int, db: Session = Depends(get_db)) -> schemas.Lote:
    """Fetch a lote and its tracks by ID."""
    lote = db.query(models.Lote).filter(models.Lote.id == lote_id).first()
    if not lote:
        raise HTTPException(status_code=404, detail="Lote not found")
    return lote


@app.get("/faixas/{faixa_id}/download")
async def download_faixa(faixa_id: int, db: Session = Depends(get_db)) -> FileResponse:
    """Return the generated audio file for a track."""
    faixa = db.query(models.Faixa).filter(models.Faixa.id == faixa_id).first()
    if not faixa:
        raise HTTPException(status_code=404, detail="Faixa not found")
    if not faixa.caminho_arquivo or not Path(faixa.caminho_arquivo).exists():
        raise HTTPException(status_code=404, detail="Audio file not available")
    return FileResponse(path=faixa.caminho_arquivo, media_type="audio/wav", filename=Path(faixa.caminho_arquivo).name)