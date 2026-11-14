"""Guarda de entrada: consulta o PromptShield antes de QUALQUER análise do conteúdo.

Todo PDF recebido é conteúdo NÃO CONFIÁVEL: pode ter instruções escondidas para o agente.
A guarda é uma camada; a proteção que não depende de modelo está em tools.py (permissões).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx

CHUNK = 9_000  # a API do PromptShield aceita até 10.000 caracteres por item


@dataclass
class GuardResult:
    decision: str            # ALLOW | REVIEW | BLOCK
    score: float
    erro: str | None = None  # preenchido se a guarda estava indisponível


class Guard(Protocol):
    def verificar(self, texto: str) -> GuardResult: ...


class NullGuard:
    """Sem guarda (testes/desenvolvimento). Deixa tudo passar, e registra que não verificou."""

    def verificar(self, texto: str) -> GuardResult:
        return GuardResult("ALLOW", 0.0, erro="guarda_desativada")


class PromptShieldGuard:
    """Cliente HTTP do PromptShield 2.0. Fail-closed: se a API cair, o documento vai para REVISÃO."""

    def __init__(self, client: httpx.Client | None = None, base_url: str = "http://localhost:8000",
                 api_key: str | None = None):
        self.client = client or httpx.Client(base_url=base_url, timeout=10)
        self.headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    def verificar(self, texto: str) -> GuardResult:
        # Divide em pedaços para um ataque no fim de um documento longo não escapar do limite de tamanho.
        pedacos = [texto[i:i + CHUNK] for i in range(0, max(len(texto), 1), CHUNK)][:100]
        try:
            r = self.client.post("/batch", json={"items": [{"text": p or " ", "source_type": "DOCUMENT"}
                                                           for p in pedacos]}, headers=self.headers)
            r.raise_for_status()
            itens = r.json()
        except (httpx.HTTPError, ValueError) as e:
            return GuardResult("REVIEW", 0.0, erro=f"guarda_indisponivel:{type(e).__name__}")  # fail-closed
        ordem = {"ALLOW": 0, "REVIEW": 1, "BLOCK": 2}
        pior = max(itens, key=lambda i: (ordem[i["decision"]], i["risk_score"]))
        return GuardResult(pior["decision"], pior["risk_score"])
