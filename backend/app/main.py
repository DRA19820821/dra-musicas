# backend/app/main.py (ATUALIZADO PARA API REAL)
"""
FastAPI application for batch music generation using the real Suno API.
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

from . import database, models, schemas
# ALTERADO: Importa cliente real em vez do stub
from . import suno_client

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
    return {"models": ["v5", "v4.5", "chirp-v3-5", "chirp-v3-0"]}

@app.post("/lotes", response_model=schemas.Lote)
async def create_lote(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(..., description="One or more JSON files"),
    modelo: str = "v5",
    prefer_wav: bool = True,
    allow_mp3_to_wav: bool = True,
    duracao_alvo: float = 240.0,  # Reduzido de 360 para 240 (4 minutos)
    extend_enabled: bool = False,  # Desabilitado por padrão pois Suno gera duração fixa
    extends_max: int = 2,
    concurrency: int = 2,
    retries: int = 3,
    timeout: float = 600.0,  # Aumentado para 10 minutos
    make_instrumental: bool = False,
    db: Session = Depends(get_db),
) -> schemas.Lote:
    if concurrency < 1 or concurrency > 4:
        raise HTTPException(status_code=400, detail="Concurrency must be between 1 and 4")

    lote = models.Lote(
        parametros={
            "modelo": modelo, "prefer_wav": prefer_wav, "allow_mp3_to_wav": allow_mp3_to_wav,
            "duracao_alvo": duracao_alvo, "extend_enabled": extend_enabled, "extends_max": extends_max,
            "concurrency": concurrency, "retries": retries, "timeout": timeout,
            "make_instrumental": make_instrumental
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
        estilo = data.get("estilo") or data.get("metadata", {}).get("estilo")
        
        if not letra or not estilo:
            raise HTTPException(
                status_code=400, 
                detail=f"File {file.filename} must contain 'letra' and 'estilo' (or metadata.estilo)"
            )

        # Extrai título da primeira linha ou usa campo específico
        titulo = data.get("titulo") or letra.strip().split("\n")[0][:100]
        
        faixa = models.Faixa(
            lote_id=lote.id,
            titulo=titulo,
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
                    duracao_alvo=p.get("duracao_alvo", 240.0),
                    extend_enabled=p.get("extend_enabled", False),
                    extends_max=p.get("extends_max", 2),
                    retries=p.get("retries", 3),
                    timeout=p.get("timeout", 600.0),
                    make_instrumental=p.get("make_instrumental", False),
                    sem=sem,
                )
            )
        )
    await asyncio.gather(*tasks)
    db.close()

async def process_faixa(
    faixa_id: int, modelo: str, prefer_wav: bool, allow_mp3_to_wav: bool,
    duracao_alvo: float, extend_enabled: bool, extends_max: int,
    retries: int, timeout: float, make_instrumental: bool, sem: asyncio.Semaphore,
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
            log_event(db, faixa_id, "Processando", "Iniciando geração via API Suno.")
            db.commit()

            attempts = 0
            gerado_com_sucesso = False
            gen_id = None
            
            while attempts < retries and not gerado_com_sucesso:
                attempts += 1
                faixa.tentativas = attempts
                log_event(db, faixa_id, "Tentativa", f"Iniciando tentativa {attempts}/{retries}.")
                db.commit()
                
                try:
                    letra_prompt = faixa.faixa_metadata.get("letra", faixa.titulo) if faixa.faixa_metadata else faixa.titulo

                    # ALTERADO: Usa cliente real
                    gen_id, urls, wav_native = await asyncio.wait_for(
                        suno_client.custom_generate(
                            title=faixa.titulo,
                            style=faixa.estilo,
                            prompt=letra_prompt,
                            model=modelo,
                            duration_target=duracao_alvo,
                            prefer_wav=prefer_wav,
                            allow_mp3_to_wav=allow_mp3_to_wav,
                            make_instrumental=make_instrumental,
                            wait_audio=True
                        ),
                        timeout=timeout
                    )
                    
                    log_event(db, faixa_id, "Geração", f"Música gerada com ID: {gen_id}")
                    faixa.ids_suno = {"initial": gen_id}
                    faixa.urls = urls
                    faixa.wav_nativo = wav_native
                    faixa.caminho_arquivo = urls["audio_url"]
                    faixa.tempo_geracao = datetime.datetime.utcnow()
                    
                    # Calcula duração aproximada do arquivo
                    file_path = Path(faixa.caminho_arquivo)
                    if file_path.exists():
                        # Aproximação: tamanho / (sample_rate * bytes_per_sample * channels)
                        # WAV 16-bit stereo = 44100 * 2 * 2 = 176400 bytes/segundo
                        faixa.duracao_final = file_path.stat().st_size / 176400
                    
                    gerado_com_sucesso = True
                    break

                except asyncio.TimeoutError:
                    log_event(db, faixa_id, "Erro", f"Timeout na tentativa {attempts}.")
                    continue
                except Exception as exc_inner:
                    log_event(db, faixa_id, "Erro", f"Falha na tentativa {attempts}: {str(exc_inner)[:200]}")
                    logger.exception(f"Erro na geração da faixa {faixa_id}")
                    continue
            
            if not gerado_com_sucesso:
                raise Exception("Todas as tentativas de geração falharam.")

            # Extensão de áudio (opcional - API Suno já gera com duração definida)
            while (extend_enabled and gen_id and faixa.duracao_final and 
                   faixa.duracao_final < duracao_alvo and 
                   faixa.extends_usados < extends_max):
                
                faixa.status = models.StatusEnum.ESTENDENDO
                log_event(db, faixa_id, "Estendendo", f"Extensão {faixa.extends_usados + 1}/{extends_max}.")
                db.commit()

                try:
                    ext_id, ext_urls, _ = await asyncio.wait_for(
                        suno_client.extend_audio(gen_id, 60.0, prefer_wav),
                        timeout=timeout
                    )
                    
                    faixa.extends_usados += 1
                    faixa.ids_suno[f"extend_{faixa.extends_usados}"] = ext_id
                    
                    ext_path = Path(ext_urls["audio_url"])
                    if ext_path.exists():
                        faixa.duracao_final += ext_path.stat().st_size / 176400
                    
                    faixa.caminho_arquivo = ext_urls["audio_url"]
                    log_event(db, faixa_id, "Estendido", f"Duração atual: {faixa.duracao_final:.2f}s.")
                    db.commit()
                except Exception as ext_err:
                    log_event(db, faixa_id, "Aviso", f"Falha ao estender: {ext_err}")
                    break

            faixa.status = models.StatusEnum.FINALIZADA
            log_event(db, faixa_id, "Finalizada", f"Música gerada com sucesso! ID: {gen_id}")
            
        except Exception as exc:
            logger.exception("Error processing faixa %s: %s", faixa_id, exc)
            faixa.status = models.StatusEnum.ERRO
            faixa.erros = {"detail": str(exc)[:500]}
            log_event(db, faixa_id, "Erro Fatal", str(exc)[:200])
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
    
    # Detecta tipo MIME correto
    file_path = Path(faixa.caminho_arquivo)
    media_type = "audio/wav" if file_path.suffix.lower() == ".wav" else "audio/mpeg"
    
    return FileResponse(
        path=faixa.caminho_arquivo, 
        media_type=media_type, 
        filename=file_path.name
    )


# 4. Monta a interface estática POR ÚLTIMO
frontend_dir = Path(__file__).resolve().parents[1] / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")