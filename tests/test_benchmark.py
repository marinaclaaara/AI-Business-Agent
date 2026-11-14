import pytest

from business_agent.benchmark import calcular


def test_formula_de_economia_com_numeros_hipoteticos_de_teste():
    # Números FICTÍCIOS, usados só para verificar a conta (não representam nenhuma medição real).
    r = calcular(manual=[300] * 5, revisao=[60] * 5, agente_ms=10, fracao_pendente=0.5)
    assert r["tempo_com_agente_s"] == 30.0  # 0,01 s + 0,5 * 60 s
    assert r["economia_por_documento_s"] == 270.0 and r["economia_percentual"] == 90.0
    assert r["horas_economizadas_por_1000_documentos"] == 75.0


def test_recusa_amostra_pequena():
    with pytest.raises(ValueError):
        calcular(manual=[300] * 4, revisao=[60] * 5, agente_ms=10, fracao_pendente=0.5)


def test_revisao_cara_demais_pode_dar_economia_negativa():
    r = calcular(manual=[20] * 5, revisao=[60] * 5, agente_ms=10, fracao_pendente=1.0)
    assert r["economia_por_documento_s"] < 0  # honestidade: o agente pode NÃO compensar
