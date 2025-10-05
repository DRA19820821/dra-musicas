"""
Database model definitions.

This module defines ORM models for the batch generation system. The
``Lote`` table corresponds to a batch of input JSON files, ``Faixa``
represents an individual track within a batch, and ``EventoFaixa``
records state transitions and logs for auditing.
"""

import datetime
import json
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    Float,
)
from sqlalchemy.orm import relationship

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

    id: int = Column(Integer, primary_key=True, index=True)
    created_at: datetime.datetime = Column(
        DateTime, default=datetime.datetime.utcnow, nullable=False
    )
    parametros: Dict[str, Any] = Column(JSON, nullable=True)
    iniciador: Optional[str] = Column(String, nullable=True)
    total_arquivos: int = Column(Integer, default=0, nullable=False)

    # Relationship to tracks within this batch
    faixas: List["Faixa"] = relationship(
        "Faixa", back_populates="lote", cascade="all, delete-orphan"
    )


class Faixa(Base):
    """Represents an individual generated track (faixa) from a prompt."""

    __tablename__ = "faixas"

    id: int = Column(Integer, primary_key=True, index=True)
    lote_id: int = Column(Integer, ForeignKey("lotes.id"), nullable=False)
    titulo: str = Column(String, nullable=False)
    estilo: str = Column(String, nullable=False)
    modelo: str = Column(String, nullable=False)
    status: StatusEnum = Column(
        Enum(StatusEnum), default=StatusEnum.SUBMETENDO, nullable=False
    )
    duracao_alvo: float = Column(Float, default=360.0, nullable=False)  # seconds
    duracao_final: Optional[float] = Column(Float, nullable=True)
    wav_nativo: bool = Column(Boolean, default=False)
    mp3_to_wav: bool = Column(Boolean, default=False)
    tentativas: int = Column(Integer, default=0)
    extends_usados: int = Column(Integer, default=0)
    ids_suno: Optional[Dict[str, Any]] = Column(JSON, nullable=True)
    urls: Optional[Dict[str, Any]] = Column(JSON, nullable=True)
    caminho_arquivo: Optional[str] = Column(String, nullable=True)
    tempo_submissao: Optional[datetime.datetime] = Column(DateTime, nullable=True)
    tempo_geracao: Optional[datetime.datetime] = Column(DateTime, nullable=True)
    tempo_download: Optional[datetime.datetime] = Column(DateTime, nullable=True)
    metadata: Optional[Dict[str, Any]] = Column(JSON, nullable=True)
    erros: Optional[Dict[str, Any]] = Column(JSON, nullable=True)

    # Relationship back to batch
    lote: Lote = relationship("Lote", back_populates="faixas")
    eventos: List["EventoFaixa"] = relationship(
        "EventoFaixa", back_populates="faixa", cascade="all, delete-orphan"
    )


class EventoFaixa(Base):
    """Captures fine‑grained events for auditing the lifecycle of a track."""

    __tablename__ = "eventos_faixa"

    id: int = Column(Integer, primary_key=True, index=True)
    faixa_id: int = Column(Integer, ForeignKey("faixas.id"), nullable=False)
    timestamp: datetime.datetime = Column(
        DateTime, default=datetime.datetime.utcnow, nullable=False
    )
    etapa: str = Column(String, nullable=False)
    detalhe: Optional[str] = Column(Text, nullable=True)

    faixa: Faixa = relationship("Faixa", back_populates="eventos")