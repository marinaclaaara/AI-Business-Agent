import pytest

from business_agent import tools
from business_agent.db import Auditoria, Outbox, Reembolso, Solicitacao, Ticket


@pytest.fixture()
def sol(db):
    s = Solicitacao(arquivo="a.pdf", sha256="x" * 64, status="PROCESSADO", categoria="reembolso")
    db.add(s)
    db.flush()
    return s


def test_agente_executa_ferramenta_permitida(db, sol):
    a = tools.executar(db, sol, "registrar_ticket", {"titulo": "t", "prioridade": "alta"})
    assert a.status == "EXECUTADA" and db.query(Ticket).count() == 1


def test_envio_de_email_so_vira_proposta_para_o_agente(db, sol):
    a = tools.executar(db, sol, "enviar_resposta_cliente", {"destinatario": "a@b.com"})
    assert a.status == "PENDENTE_APROVACAO" and db.query(Outbox).count() == 0


def test_agente_NAO_pode_aprovar_reembolso_e_a_tentativa_e_auditada(db, sol):
    a = tools.executar(db, sol, "aprovar_reembolso", {"valor_brl": 9999}, ator="agente")
    assert a.status == "NEGADA" and db.query(Reembolso).count() == 0
    log = db.query(Auditoria).filter_by(evento="tool:aprovar_reembolso").one()
    assert log.permitido is False


def test_humano_pode_aprovar_reembolso(db, sol):
    tools.executar(db, sol, "aprovar_reembolso", {"valor_brl": 100.0}, ator="humano:Carla")
    r = db.query(Reembolso).one()
    assert r.aprovado_por == "humano:Carla" and r.valor_brl == 100.0


def test_ferramenta_desconhecida_e_rejeitada(db, sol):
    with pytest.raises(tools.FerramentaDesconhecida):
        tools.executar(db, sol, "apagar_banco", {})


def test_aprovar_pendentes_executa_e_rejeitar_nao(db, sol):
    tools.executar(db, sol, "gerar_rascunho_resposta", {"texto": "ola"})
    tools.executar(db, sol, "enviar_resposta_cliente", {"destinatario": "a@b.com"})
    assert tools.decidir_pendentes(db, sol, "Carla", aprovar=True) == 1
    assert db.query(Outbox).count() == 1 and db.query(Outbox).one().corpo == "ola"

    tools.executar(db, sol, "enviar_resposta_cliente", {"destinatario": "c@d.com"})
    tools.decidir_pendentes(db, sol, "Carla", aprovar=False)
    assert db.query(Outbox).count() == 1  # a segunda foi rejeitada: nada novo saiu
