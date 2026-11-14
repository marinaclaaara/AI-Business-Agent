"""Persistência (SQLAlchemy 2.0). Padrão: SQLite local. Para PostgreSQL basta mudar DATABASE_URL
(ex.: postgresql+psycopg://user:senha@host/db). !! O caminho PostgreSQL NÃO foi testado aqui. !!

Tabelas:
  solicitacoes  - uma linha por PDF processado (resultado, status, tempo medido)
  acoes         - ações que o agente tentou: executada, aguardando aprovação, negada ou rejeitada
  auditoria     - trilha imutável de TUDO que aconteceu (quem, o quê, quando)
  tickets / outbox / reembolsos - efeitos das ferramentas (simulados: nada sai da máquina)
"""
from __future__ import annotations

import os
from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


def agora() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Solicitacao(Base):
    __tablename__ = "solicitacoes"
    id: Mapped[int] = mapped_column(primary_key=True)
    arquivo: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # idempotência: mesmo PDF = 1 registro
    status: Mapped[str] = mapped_column(String(32), index=True)
    # PROCESSADO | PENDENTE_REVISAO | BLOQUEADO | APROVADA | REJEITADA | ERRO
    categoria: Mapped[str | None] = mapped_column(String(32), nullable=True)
    prioridade: Mapped[str | None] = mapped_column(String(16), nullable=True)
    resumo: Mapped[str | None] = mapped_column(Text, nullable=True)
    campos: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    justificativa: Mapped[list | None] = mapped_column(JSON, nullable=True)
    confianca: Mapped[float | None] = mapped_column(Float, nullable=True)
    motivos_revisao: Mapped[list | None] = mapped_column(JSON, nullable=True)
    provedor: Mapped[str | None] = mapped_column(String(32), nullable=True)
    guarda_decisao: Mapped[str | None] = mapped_column(String(8), nullable=True)
    guarda_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    rascunho_resposta: Mapped[str | None] = mapped_column(Text, nullable=True)
    tempo_ms: Mapped[float | None] = mapped_column(Float, nullable=True)  # medido com relógio monotônico
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=agora)
    revisor: Mapped[str | None] = mapped_column(String(80), nullable=True)
    revisado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    nota_revisao: Mapped[str | None] = mapped_column(Text, nullable=True)


class Acao(Base):
    __tablename__ = "acoes"
    id: Mapped[int] = mapped_column(primary_key=True)
    solicitacao_id: Mapped[int] = mapped_column(ForeignKey("solicitacoes.id"), index=True)
    ferramenta: Mapped[str] = mapped_column(String(48))
    argumentos: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(24))  # EXECUTADA | PENDENTE_APROVACAO | NEGADA | REJEITADA
    ator: Mapped[str] = mapped_column(String(80))    # "agente" ou "humano:<nome>"
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=agora)
    decidido_por: Mapped[str | None] = mapped_column(String(80), nullable=True)


class Auditoria(Base):
    __tablename__ = "auditoria"
    id: Mapped[int] = mapped_column(primary_key=True)
    solicitacao_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    ator: Mapped[str] = mapped_column(String(80))
    evento: Mapped[str] = mapped_column(String(64))
    detalhe: Mapped[str] = mapped_column(Text, default="")
    permitido: Mapped[bool] = mapped_column(Boolean, default=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=agora)


class Ticket(Base):
    __tablename__ = "tickets"
    id: Mapped[int] = mapped_column(primary_key=True)
    solicitacao_id: Mapped[int] = mapped_column(ForeignKey("solicitacoes.id"))
    titulo: Mapped[str] = mapped_column(String(200))
    prioridade: Mapped[str] = mapped_column(String(16))
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=agora)


class Outbox(Base):
    """E-mails 'enviados'. SIMULADO: grava a mensagem, não envia nada pela rede."""
    __tablename__ = "outbox"
    id: Mapped[int] = mapped_column(primary_key=True)
    solicitacao_id: Mapped[int] = mapped_column(ForeignKey("solicitacoes.id"))
    destinatario: Mapped[str] = mapped_column(String(200))
    corpo: Mapped[str] = mapped_column(Text)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=agora)


class Reembolso(Base):
    """Reembolsos aprovados. SIMULADO. Só um humano consegue criar uma linha aqui."""
    __tablename__ = "reembolsos"
    id: Mapped[int] = mapped_column(primary_key=True)
    solicitacao_id: Mapped[int] = mapped_column(ForeignKey("solicitacoes.id"))
    valor_brl: Mapped[float] = mapped_column(Float)
    aprovado_por: Mapped[str] = mapped_column(String(80))
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=agora)


def criar_sessionmaker(url: str | None = None) -> sessionmaker[Session]:
    url = url or os.getenv("DATABASE_URL", "sqlite:///business_agent.db")
    args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    # StaticPool mantém UM banco em memória compartilhado entre threads (necessário p/ testes com sqlite://)
    from sqlalchemy.pool import StaticPool
    extra = {"poolclass": StaticPool} if url in ("sqlite://", "sqlite:///:memory:") else {}
    engine = create_engine(url, connect_args=args, **extra)
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)
