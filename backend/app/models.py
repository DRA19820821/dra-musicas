# backend/app/models.py (CORRIGIDO)
"""
Database model definitions.
"""
import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    Float,
)
from sqlalchemy.orm import relationship, Mapped, mapped_column

from .database import Base


class StatusEnum(str, Enum):
    """Possible statuses for a track (faixa)."""
    SUBMETENDO = "submetendo"
    GERANDO = "gerando"
    OBTENDO = "obtendo"
    ESTENDENDO = "estendendo"
    BAIXANDO = "baixando"
    FINALIZADA = "finalizada"
    ERRO = "erro"


class Lote(Base):
    """Represents a batch of input JSON files processed together."""
    __tablename__ = "lotes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow, nullable=False
    )
    parametros: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    iniciador: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    total_arquivos: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    faixas: Mapped[List["Faixa"]] = relationship(
        "Faixa", back_populates="lote", cascade="all, delete-orphan"
    )


class Faixa(Base):
    """Represents an individual generated track (faixa) from a prompt."""
    __tablename__ = "faixas"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    lote_id: Mapped[int] = mapped_column(Integer, ForeignKey("lotes.id"), nullable=False)
    titulo: Mapped[str] = mapped_column(String, nullable=False)
    estilo: Mapped[str] = mapped_column(String, nullable=False)
    modelo: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[StatusEnum] = mapped_column(default=StatusEnum.SUBMETENDO, nullable=False)
    duracao_alvo: Mapped[float] = mapped_column(Float, default=360.0, nullable=False)
    duracao_final: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    wav_nativo: Mapped[bool] = mapped_column(Boolean, default=False)
    mp3_to_wav: Mapped[bool] = mapped_column(Boolean, default=False)
    tentativas: Mapped[int] = mapped_column(Integer, default=0)
    extends_usados: Mapped[int] = mapped_column(Integer, default=0)
    ids_suno: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    urls: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    caminho_arquivo: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    tempo_submissao: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    tempo_geracao: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    tempo_download: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    # Renomeado de 'metadata' para 'faixa_metadata'
    faixa_metadata: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    erros: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    lote: Mapped["Lote"] = relationship("Lote", back_populates="faixas")
    eventos: Mapped[List["EventoFaixa"]] = relationship(
        "EventoFaixa", back_populates="faixa", cascade="all, delete-orphan"
    )


class EventoFaixa(Base):
    """Captures fine‑grained events for auditing the lifecycle of a track."""
    __tablename__ = "eventos_faixa"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    faixa_id: Mapped[int] = mapped_column(Integer, ForeignKey("faixas.id"), nullable=False)
    timestamp: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow, nullable=False
    )
    etapa: Mapped[str] = mapped_column(String, nullable=False)
    detalhe: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    faixa: Mapped["Faixa"] = relationship("Faixa", back_populates="eventos")