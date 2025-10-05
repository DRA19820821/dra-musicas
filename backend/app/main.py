# backend/app/main.py (VERSÃO COM ORDEM DE ROTAS CORRIGIDA)
"""
FastAPI application for batch music generation using the Suno API stub.
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
from fastapi.staticfiles import StaticFiles

from . import database, models, schemas, suno_client_stub

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 1. Inicia a aplicação FastAPI
app = FastAPI(title="Suno Batch Music Processor")

# 2. Define funções auxiliares e eventos de startup
def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()

def log_event(db: Session, faixa_id: int, etapa: str, detalhe: str = None):
    """Cria e salva um registro de evento para uma faixa."""
    evento = models.EventoFaixa(faixa_id=faixa_id, etapa=etapa, detalhe=detalhe)
    db.add(evento)
    db.commit()

@app.on_event("startup")
async def startup_event() -> None:
    database.init_db()
    logger.info("Application startup complete.")


# 3. Define TODAS as rotas da API
@app.get("/models", summary="List available Suno models")
async def list_models() -> dict:
    """Return a list of available model identifiers."""
    return {"models": ["v5", "v4.5"]}

@app.post("/lotes", response_model=schemas.Lote)
async def create_lote(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(..., description="One or more JSON files"),
    modelo: str = "v5",
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
    if concurrency < 1 or concurrency > 4:
        raise HTTPException(status_code=400, detail="Concurrency must be between 1 and 4")

    lote = models.Lote(
        parametros={
            "modelo": modelo, "prefer_wav": prefer_wav, "allow_mp3_to_wav": allow_mp3_to_wav,
            "duracao_alvo": duracao_alvo, "extend_enabled": extend_enabled, "extends_max": extends_max,
            "concurrency": concurrency, "retries": retries, "timeout": timeout,
        },
        total_arquivos=len(files),
    )
    db.add(lote)
    db.commit()
    db.refresh(lote)

    for file in files:
        contents = await file.read()
        try:
            data = json.loads(contents.decode("utf-8"))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"File {file.filename} is not valid JSON: {exc}")

        letra = data.get("letra")
        estilo = data.get("metadata", {}).get("estilo")
        
        if not letra or not estilo:
            raise HTTPException(status_code=400, detail=f"File {file.filename} must contain 'letra' and 'estilo'")

        title_line = letra.strip().split("\n")[0]
        faixa = models.Faixa(
            lote_id=lote.id,
            titulo=title_line,
            estilo=estilo,
            modelo=modelo,
            duracao_alvo=duracao_alvo,
            faixa_metadata=data,
        )
        db.add(faixa)
        db.commit()
        db.refresh(faixa)
        log_event(db, faixa.id, "Submetida", f"Faixa '{faixa.titulo}' adicionada ao lote {lote.id}.")

    background_tasks.add_task(
        process_lote, lote_id=lote.id
    )

    lote = db.query(models.Lote).filter(models.Lote.id == lote.id).first()
    return lote

async def process_lote(lote_id: int):
    db = database.SessionLocal()
    lote = db.query(models.Lote).filter(models.Lote.id == lote_id).first()
    if not lote:
        db.close()
        return

    p = lote.parametros
    sem = asyncio.Semaphore(p.get("concurrency", 2))
    tasks = []

    for faixa in lote.faixas:
        tasks.append(
            asyncio.create_task(
                process_faixa(
                    faixa_id=faixa.id,
                    modelo=p.get("modelo", "v5"),
                    prefer_wav=p.get("prefer_wav", True),
                    allow_mp3_to_wav=p.get("allow_mp3_to_wav", True),
                    duracao_alvo=p.get("duracao_alvo", 360.0),
                    extend_enabled=p.get("extend_enabled", True),
                    extends_max=p.get("extends_max", 2),
                    retries=p.get("retries", 3),
                    timeout=p.get("timeout", 480.0),
                    sem=sem,
                )
            )
        )
    await asyncio.gather(*tasks)
    db.close()

async def process_faixa(
    faixa_id: int, modelo: str, prefer_wav: bool, allow_mp3_to_wav: bool,
    duracao_alvo: float, extend_enabled: bool, extends_max: int,
    retries: int, timeout: float, sem: asyncio.Semaphore,
):
    async with sem:
        db = database.SessionLocal()
        faixa = db.query(models.Faixa).filter(models.Faixa.id == faixa_id).first()
        if not faixa:
            db.close()
            return
        
        try:
            faixa.tempo_submissao = datetime.datetime.utcnow()
            faixa.status = models.StatusEnum.GERANDO
            log_event(db, faixa_id, "Processando", "Iniciando processo de geração.")
            db.commit()

            attempts = 0
            gerado_com_sucesso = False
            while attempts < retries and not gerado_com_sucesso:
                attempts += 1
                faixa.tentativas = attempts
                log_event(db, faixa_id, "Tentativa", f"Iniciando tentativa de geração {attempts}/{retries}.")
                db.commit()
                
                try:
                    letra_prompt = faixa.faixa_metadata.get("letra", faixa.titulo) if faixa.faixa_metadata else faixa.titulo

                    gen_id, urls, wav_native = await asyncio.wait_for(
                        suno_client_stub.custom_generate(
                            faixa.titulo, faixa.estilo, letra_prompt,
                            modelo, duracao_alvo, prefer_wav, allow_mp3_to_wav,
                        ),
                        timeout=timeout
                    )
                    
                    log_event(db, faixa_id, "Geração", f"ID de geração inicial: {gen_id}.")
                    faixa.ids_suno = {"initial": gen_id}
                    faixa.urls = urls
                    faixa.wav_nativo = wav_native
                    faixa.caminho_arquivo = urls["audio_url"]
                    faixa.tempo_geracao = datetime.datetime.utcnow()
                    
                    file_path = Path(faixa.caminho_arquivo)
                    if file_path.exists():
                        faixa.duracao_final = file_path.stat().st_size / (44100 * 2)
                    
                    gerado_com_sucesso = True
                    break

                except asyncio.TimeoutError:
                    log_event(db, faixa_id, "Erro", f"Tentativa {attempts} falhou por timeout.")
                    continue
                except Exception as exc_inner:
                    log_event(db, faixa_id, "Erro", f"Tentativa {attempts} falhou: {exc_inner}")
                    continue
            
            if not gerado_com_sucesso:
                raise Exception("Todas as tentativas de geração falharam.")

            while extend_enabled and faixa.duracao_final and faixa.duracao_final < duracao_alvo and faixa.extends_usados < extends_max:
                faixa.status = models.StatusEnum.ESTENDENDO
                log_event(db, faixa_id, "Estendendo", f"Tentativa de extensão {faixa.extends_usados + 1}/{extends_max}.")
                db.commit()

                ext_id, ext_urls, _ = await suno_client_stub.extend_audio(gen_id, 60.0, prefer_wav)
                faixa.extends_usados += 1
                faixa.ids_suno[f"extend_{faixa.extends_usados}"] = ext_id
                
                ext_path = Path(ext_urls["audio_url"])
                if ext_path.exists():
                    faixa.duracao_final += ext_path.stat().st_size / (44100 * 2)
                
                faixa.caminho_arquivo = ext_urls["audio_url"]
                log_event(db, faixa_id, "Estendido", f"Duração atual: {faixa.duracao_final:.2f}s.")
                db.commit()

            faixa.status = models.StatusEnum.FINALIZADA
            log_event(db, faixa_id, "Finalizada", "Processamento concluído com sucesso.")
            
        except Exception as exc:
            logger.exception("Error processing faixa %s: %s", faixa_id, exc)
            faixa.status = models.StatusEnum.ERRO
            faixa.erros = {"detail": str(exc)}
            log_event(db, faixa_id, "Erro Fatal", str(exc))
        finally:
            faixa.tempo_download = datetime.datetime.utcnow()
            db.commit()
            db.close()

@app.get("/lotes/{lote_id}", response_model=schemas.Lote)
async def get_lote(lote_id: int, db: Session = Depends(get_db)) -> schemas.Lote:
    lote = db.query(models.Lote).filter(models.Lote.id == lote_id).first()
    if not lote:
        raise HTTPException(status_code=404, detail="Lote not found")
    return lote


@app.get("/faixas/{faixa_id}/download")
async def download_faixa(faixa_id: int, db: Session = Depends(get_db)) -> FileResponse:
    faixa = db.query(models.Faixa).filter(models.Faixa.id == faixa_id).first()
    if not faixa:
        raise HTTPException(status_code=404, detail="Faixa not found")
    if not faixa.caminho_arquivo or not Path(faixa.caminho_arquivo).exists():
        raise HTTPException(status_code=404, detail="Audio file not available")
    return FileResponse(path=faixa.caminho_arquivo, media_type="audio/wav", filename=Path(faixa.caminho_arquivo).name)


# 4. Monta a interface estática POR ÚLTIMO
frontend_dir = Path(__file__).resolve().parents[1] / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")