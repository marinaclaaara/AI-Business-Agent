"""Cálculo do tempo economizado. NÃO inventa números: exige tempos medidos por uma pessoa.

Entrada: CSV com colunas  tipo,arquivo,segundos   (tipo = manual | revisao)
  manual  = quanto tempo uma pessoa levou para tratar o PDF SEM o agente (ler, classificar, extrair, resumir, registrar)
  revisao = quanto tempo uma pessoa levou para revisar/aprovar no painel um documento que o agente deixou pendente
Fração de documentos que vão para revisão: lida de results/evaluation.json (medida) ou informada.

  tempo_com_agente = tempo_do_agente + fração_pendente * tempo_médio_de_revisão
  economia         = tempo_manual_médio - tempo_com_agente
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
from pathlib import Path


def calcular(manual: list[float], revisao: list[float], agente_ms: float, fracao_pendente: float) -> dict:
    if len(manual) < 5 or len(revisao) < 5:
        raise ValueError("Meça pelo menos 5 documentos de cada tipo (manual e revisão) para ter um número defensável.")
    m, r = statistics.mean(manual), statistics.mean(revisao)
    com_agente = agente_ms / 1000 + fracao_pendente * r
    return {
        "n_manual": len(manual), "n_revisao": len(revisao),
        "tempo_manual_medio_s": round(m, 1), "desvio_manual_s": round(statistics.stdev(manual), 1),
        "tempo_revisao_medio_s": round(r, 1), "tempo_agente_ms": agente_ms, "fracao_pendente": fracao_pendente,
        "tempo_com_agente_s": round(com_agente, 1),
        "economia_por_documento_s": round(m - com_agente, 1),
        "economia_percentual": round(100 * (m - com_agente) / m, 1),
        "horas_economizadas_por_1000_documentos": round((m - com_agente) * 1000 / 3600, 1),
    }


def ler_csv(caminho: Path) -> tuple[list[float], list[float]]:
    manual, revisao = [], []
    with open(caminho, encoding="utf-8") as f:
        for linha in csv.DictReader(f):
            (manual if linha["tipo"] == "manual" else revisao).append(float(linha["segundos"]))
    return manual, revisao


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tempos", type=Path, required=True, help="CSV medido: tipo,arquivo,segundos")
    ap.add_argument("--avaliacao", type=Path, default=Path("results/evaluation.json"))
    a = ap.parse_args()
    ev = json.loads(a.avaliacao.read_text(encoding="utf-8"))
    normais = ev["status_final_normais"]
    fracao = normais.get("PENDENTE_REVISAO", 0) / max(sum(normais.values()), 1)
    manual, revisao = ler_csv(a.tempos)
    out = calcular(manual, revisao, agente_ms=ev["tempo_por_documento_ms"]["media"], fracao_pendente=round(fracao, 3))
    print(json.dumps(out, indent=2, ensure_ascii=False))
