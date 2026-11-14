import pytest
from fastapi.testclient import TestClient

from business_agent.api import create_app
from business_agent.providers import RuleBasedProvider

from .conftest import DOC_REEMBOLSO, GuardaFixa, fazer_pdf


def _cliente(guarda=None, chaves=None):
    app = create_app("sqlite://", provider=RuleBasedProvider(), guard=guarda or GuardaFixa(), api_keys=chaves or set())
    return TestClient(app), app


def _enviar(c, texto=DOC_REEMBOLSO, nome="a.pdf", headers=None):
    return c.post("/api/documentos", files={"arquivo": (nome, fazer_pdf(texto), "application/pdf")}, headers=headers)


def test_upload_lista_e_detalhe_com_auditoria():
    c, _ = _cliente()
    r = _enviar(c)
    assert r.status_code == 200 and r.json()["categoria"] == "reembolso"
    sid = r.json()["id"]
    assert [s["id"] for s in c.get("/api/solicitacoes").json()] == [sid]
    d = c.get(f"/api/solicitacoes/{sid}").json()
    assert [a["ferramenta"] for a in d["acoes"]] == ["registrar_ticket", "gerar_rascunho_resposta",
                                                     "enviar_resposta_cliente"]
    assert any(t["evento"] == "recebido" for t in d["auditoria"]) and d["auditoria"][0]["ator"] == "agente"


def test_upload_de_arquivo_invalido_devolve_422():
    c, _ = _cliente()
    r = c.post("/api/documentos", files={"arquivo": ("x.pdf", b"nao e pdf", "application/pdf")})
    assert r.status_code == 422


def test_aprovacao_humana_executa_o_envio_e_registra_quem_aprovou():
    c, app = _cliente()
    sid = _enviar(c).json()["id"]
    r = c.post(f"/api/solicitacoes/{sid}/revisao", json={"decisao": "aprovar", "revisor": "Carla"})
    assert r.status_code == 200 and r.json()["status"] == "APROVADA" and r.json()["revisor"] == "Carla"
    d = c.get(f"/api/solicitacoes/{sid}").json()
    assert d["acoes"][-1]["status"] == "EXECUTADA" and d["acoes"][-1]["decidido_por"] == "humano:Carla"


def test_rejeicao_nao_envia_nada():
    c, app = _cliente()
    sid = _enviar(c).json()["id"]
    c.post(f"/api/solicitacoes/{sid}/revisao", json={"decisao": "rejeitar", "revisor": "Carla"})
    assert c.get(f"/api/solicitacoes/{sid}").json()["acoes"][-1]["status"] == "REJEITADA"


def test_nao_revisa_duas_vezes_e_valida_entrada():
    c, _ = _cliente()
    sid = _enviar(c).json()["id"]
    ok = {"decisao": "aprovar", "revisor": "Carla"}
    assert c.post(f"/api/solicitacoes/{sid}/revisao", json=ok).status_code == 200
    assert c.post(f"/api/solicitacoes/{sid}/revisao", json=ok).status_code == 409
    assert c.post(f"/api/solicitacoes/{sid}/revisao", json={"decisao": "talvez", "revisor": "C"}).status_code == 422
    assert c.post("/api/solicitacoes/999/revisao", json=ok).status_code == 404


def test_documento_bloqueado_nao_pode_ser_aprovado():
    c, _ = _cliente(GuardaFixa("BLOCK", 0.9))
    sid = _enviar(c).json()["id"]
    assert c.get(f"/api/solicitacoes/{sid}").json()["status"] == "BLOQUEADO"
    r = c.post(f"/api/solicitacoes/{sid}/revisao", json={"decisao": "aprovar", "revisor": "Carla"})
    assert r.status_code == 409
    ok = c.post(f"/api/solicitacoes/{sid}/revisao", json={"decisao": "rejeitar", "revisor": "Carla"})
    assert ok.status_code == 200


def test_reembolso_so_existe_depois_de_decisao_humana_explicita():
    c, app = _cliente()
    sid = _enviar(c).json()["id"]
    r = c.post(f"/api/solicitacoes/{sid}/revisao",
               json={"decisao": "aprovar", "revisor": "Carla", "aprovar_reembolso": True})
    assert r.status_code == 200
    ev = [t for t in c.get(f"/api/solicitacoes/{sid}").json()["auditoria"] if t["evento"] == "tool:aprovar_reembolso"]
    assert ev and ev[0]["ator"] == "humano:Carla" and ev[0]["permitido"] is True


def test_reembolso_exige_categoria_reembolso():
    c, _ = _cliente()
    sid = _enviar(c, "Cliente: Ana\nSolicito orçamento.\nValor: R$ 100,00", nome="b.pdf").json()["id"]
    r = c.post(f"/api/solicitacoes/{sid}/revisao",
               json={"decisao": "aprovar", "revisor": "Carla", "aprovar_reembolso": True})
    assert r.status_code == 422


def test_autenticacao_bearer():
    c, _ = _cliente(chaves={"segredo"})
    assert c.get("/health").status_code == 200 and c.get("/").status_code == 200  # painel e health são públicos
    assert c.get("/api/solicitacoes").status_code == 401
    assert _enviar(c).status_code == 401
    assert c.get("/api/solicitacoes", headers={"Authorization": "Bearer errada"}).status_code == 401
    assert _enviar(c, headers={"Authorization": "Bearer segredo"}).status_code == 200


def test_relatorio_json_e_markdown_so_com_dados_reais():
    c, _ = _cliente()
    _enviar(c)
    r = c.get("/api/relatorio").json()
    assert r["total"] == 1 and r["por_categoria"] == {"reembolso": 1} and r["tempo_medio_processamento_ms"] > 0
    md = c.get("/api/relatorio.md").text
    assert md.startswith("# Relatório de triagem") and "reembolso" in md


def test_cabecalhos_de_seguranca_e_painel_estatico():
    c, _ = _cliente()
    r = c.get("/")
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "script-src" not in r.text and "<script src=\"/static/app.js\"" in r.text  # sem JS inline
    assert c.get("/static/app.js").status_code == 200




@pytest.mark.parametrize("rota", ["/api/solicitacoes/abc", "/api/solicitacoes/0"])
def test_rotas_com_id_invalido(rota):
    c, _ = _cliente()
    assert c.get(rota).status_code in (404, 422)
