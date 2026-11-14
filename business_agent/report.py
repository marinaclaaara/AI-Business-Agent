"""Relatório estruturado do lote (JSON e Markdown). Só usa dados REAIS do banco."""
from __future__ import annotations

import statistics
from collections import Counter

from sqlalchemy.orm import Session

from .db import Acao, Solicitacao
from .schemas import Prioridade

PESO = {p.value: i for i, p in enumerate(reversed(list(Prioridade)))}  # urgente=0 ... baixa=3


def gerar_relatorio(db: Session) -> dict:
    sols = db.query(Solicitacao).all()
    tempos = [s.tempo_ms for s in sols if s.tempo_ms is not None]
    fila = sorted((s for s in sols if s.status == "PENDENTE_REVISAO"), key=lambda s: PESO.get(s.prioridade or "", 9))
    return {
        "total": len(sols),
        "por_status": dict(Counter(s.status for s in sols)),
        "por_categoria": dict(Counter(s.categoria or "sem_categoria" for s in sols)),
        "por_prioridade": dict(Counter(s.prioridade or "sem_prioridade" for s in sols)),
        "guarda": dict(Counter(s.guarda_decisao or "nao_verificado" for s in sols)),
        "acoes": dict(Counter(a.status for a in db.query(Acao).all())),
        "tempo_medio_processamento_ms": round(statistics.mean(tempos), 2) if tempos else None,
        "fila_de_revisao": [{"id": s.id, "arquivo": s.arquivo, "prioridade": s.prioridade, "categoria": s.categoria,
                             "motivos": s.motivos_revisao} for s in fila[:50]],
    }


def para_markdown(r: dict) -> str:
    def tab(titulo: str, d: dict) -> str:
        linhas = "\n".join(f"| {k} | {v} |" for k, v in sorted(d.items(), key=lambda kv: -kv[1]))
        return f"### {titulo}\n| Valor | Qtd |\n|---|---|\n{linhas}\n"
    fila = "\n".join(
        f"- #{i['id']} {i['arquivo']} ({i['prioridade']}/{i['categoria']}): {', '.join(i['motivos'] or [])}"
        for i in r["fila_de_revisao"]) or "_Fila vazia._"
    tempo = r["tempo_medio_processamento_ms"]
    return (f"# Relatório de triagem\n\nTotal de solicitações: **{r['total']}**. "
            f"Tempo médio de processamento (medido): **{tempo if tempo is not None else 'n/d'} ms**.\n\n"
            + tab("Status", r["por_status"]) + tab("Categoria", r["por_categoria"])
            + tab("Prioridade", r["por_prioridade"]) + tab("Guarda (PromptShield)", r["guarda"])
            + tab("Ações do agente", r["acoes"]) + f"\n### Fila de revisão humana (mais urgentes primeiro)\n{fila}\n")
