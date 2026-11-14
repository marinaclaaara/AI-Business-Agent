"""Contratos de dados (Pydantic). Tudo que sai de um provedor (regras OU LLM) é VALIDADO aqui.

Por que validar a saída de um LLM? Porque ele pode devolver um JSON malformado, uma
categoria que não existe ou um valor negativo. O schema transforma "texto livre" em dado
confiável ou em um erro explícito, e nunca em um estado inválido dentro do sistema.
"""
from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class Categoria(StrEnum):
    REEMBOLSO = "reembolso"
    SUPORTE = "suporte_tecnico"
    COTACAO = "cotacao"
    RECLAMACAO = "reclamacao"
    CANCELAMENTO = "cancelamento"
    OUTROS = "outros"


class Prioridade(StrEnum):
    BAIXA = "baixa"
    MEDIA = "media"
    ALTA = "alta"
    URGENTE = "urgente"


ORDEM_PRIORIDADE = [Prioridade.BAIXA, Prioridade.MEDIA, Prioridade.ALTA, Prioridade.URGENTE]


class Campos(BaseModel):
    cliente: str | None = None
    email: str | None = None
    pedido: str | None = None
    valor_brl: float | None = Field(default=None, ge=0)
    prazo: str | None = None  # dd/mm/aaaa, quando o documento cita um prazo


class Analise(BaseModel):
    categoria: Categoria
    prioridade: Prioridade
    campos: Campos
    resumo: str = Field(max_length=600)
    confianca: float = Field(ge=0, le=1)
    justificativa: list[str] = Field(default_factory=list, description="Sinais que levaram à decisão (auditável).")
