# backend/app/schemas.py (CORRIGIDO)
"""
Pydantic schemas for request and response models.
"""

import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ConfigDict

from .models import StatusEnum


# Novo schema para os eventos de log
class EventoFaixa(BaseModel):
    id: int
    timestamp: datetime.datetime
    etapa: str
    detalhe: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class FaixaBase(BaseModel):
    titulo: str
    estilo: str
    modelo: str
    duracao_alvo: float = Field(
        360.0, description="Target duration for the track in seconds"
    )
    faixa_metadata: Optional[Dict[str, Any]] = None


class FaixaCreate(FaixaBase):
    letra: str = Field(..., description="Full lyrics prompt")


class Faixa(FaixaBase):
    id: int
    lote_id: int
    status: StatusEnum
    duracao_final: Optional[float] = None
    wav_nativo: bool
    mp3_to_wav: bool
    tentativas: int
    extends_usados: int
    ids_suno: Optional[Dict[str, Any]] = None
    urls: Optional[Dict[str, Any]] = None
    caminho_arquivo: Optional[str] = None
    tempo_submissao: Optional[datetime.datetime] = None
    tempo_geracao: Optional[datetime.datetime] = None
    tempo_download: Optional[datetime.datetime] = None
    erros: Optional[Dict[str, Any]] = None
    # Adicionada a lista de eventos para ser retornada na API
    eventos: List[EventoFaixa] = []

    # 'orm_mode' foi atualizado para 'from_attributes' em Pydantic V2
    model_config = ConfigDict(from_attributes=True)


class LoteCreate(BaseModel):
    modelo: str = Field(..., description="Selected Suno model, e.g. v4.5 or v5")
    prefer_wav: bool = Field(True, description="Prefer native WAV output")
    allow_mp3_to_wav: bool = Field(
        True, description="Convert MP3 to WAV if native WAV is unavailable"
    )
    duracao_alvo: float = Field(
        360.0, description="Target duration per track in seconds"
    )
    extend_enabled: bool = Field(
        True, description="Allow extending tracks if shorter than target"
    )
    extends_max: int = Field(2, description="Maximum number of extends to attempt")
    concurrency: int = Field(2, ge=1, le=4, description="Number of concurrent tasks")
    retries: int = Field(3, description="Number of generation retries per track")
    timeout: float = Field(
        480.0, description="Generation timeout per attempt in seconds"
    )
    arquivos: List[str] = Field(
        ..., description="Names of uploaded JSON files on the server"
    )


class Lote(BaseModel):
    id: int
    created_at: datetime.datetime
    parametros: Optional[Dict[str, Any]] = None
    iniciador: Optional[str] = None
    total_arquivos: int
    faixas: List[Faixa] = []

    model_config = ConfigDict(from_attributes=True)