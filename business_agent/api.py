"""API do AI Business Agent + painel de revisão humana (arquivos estáticos).

Rodar: uvicorn business_agent.api:create_app --factory   (fábrica: nada é criado só por importar o módulo)

Segurança:
  * chave Bearer opcional (BUSINESS_AGENT_API_KEYS) em todas as rotas /api;
  * conteúdo de PDF é NÃO CONFIÁVEL: o painel usa textContent (nunca innerHTML) e a CSP bloqueia scripts inline;
  * upload: limite de 10 MB e checagem da assinatura %PDF.
"""
from __future__ import annotations

import logging
import os
import secrets
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import __version__, tools
from .agent import Agente
from .db import Acao, Auditoria, Solicitacao, agora, criar_sessionmaker
from .guard import Guard, NullGuard, PromptShieldGuard
from .pdf_reader import MAX_BYTES
from .providers import AnthropicProvider, Provider, RuleBasedProvider
from .report import gerar_relatorio, para_markdown

log = logging.getLogger("business_agent")
STATIC = Path(__file__).parent / "static"


class Revisao(BaseModel):
    decisao: Literal["aprovar", "rejeitar"]
    revisor: str = Field(min_length=2, max_length=80)
    nota: str | None = Field(default=None, max_length=1000)
    aprovar_reembolso: bool = False


def _sol_dict(s: Solicitacao) -> dict:
    return {c.name: (getattr(s, c.name).isoformat() if hasattr(getattr(s, c.name), "isoformat") else getattr(s, c.name))
            for c in Solicitacao.__table__.columns}


def create_app(db_url: str | None = None, provider: Provider | None = None, guard: Guard | None = None,
               api_keys: set[str] | None = None) -> FastAPI:
    app = FastAPI(title="AI Business Agent", version=__version__)
    Sessao = criar_sessionmaker(db_url)
    if provider is None:
        provider = AnthropicProvider() if os.getenv("AGENT_PROVIDER") == "anthropic" else RuleBasedProvider()
    if guard is None:
        url = os.getenv("PROMPTSHIELD_URL")
        guard = PromptShieldGuard(base_url=url, api_key=os.getenv("PROMPTSHIELD_API_KEY")) if url else NullGuard()
        if not url:
            log.warning("PROMPTSHIELD_URL não definido: SEM guarda de prompt injection.")
    agente = Agente(provider, guard)
    chaves = api_keys if api_keys is not None else {k.strip() for k in
                                                    os.getenv("BUSINESS_AGENT_API_KEYS", "").split(",") if k.strip()}

    def db_sessao():
        with Sessao() as db:
            yield db

    def autenticar(authorization: str | None = Header(default=None)) -> None:
        if not chaves:
            return
        esquema, _, token = (authorization or "").partition(" ")
        if esquema.lower() != "bearer" or not any(secrets.compare_digest(token, k) for k in chaves):
            raise HTTPException(401, "Credenciais inválidas.", headers={"WWW-Authenticate": "Bearer"})

    @app.middleware("http")
    async def cabecalhos_de_seguranca(request: Request, call_next):
        resp = await call_next(request)
        # CSP estrita: sem scripts inline, sem recursos externos. Mitiga XSS vindo de texto de PDF.
        resp.headers["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none'"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        return resp

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/", include_in_schema=False)
    def painel():
        return FileResponse(STATIC / "index.html")

    @app.get("/health")
    def health():
        return {"status": "ok", "provider": provider.nome, "guard": type(guard).__name__}

    rota = {"dependencies": [Depends(autenticar)]}

    @app.post("/api/documentos", **rota)
    async def enviar(arquivo: UploadFile = File(...), db: Session = Depends(db_sessao)):
        conteudo = await arquivo.read(MAX_BYTES + 1)
        sol = agente.processar(db, arquivo.filename or "sem_nome.pdf", conteudo)
        if sol.status == "ERRO":  # o registro fica na auditoria, mas o cliente recebe um erro claro
            raise HTTPException(422, "; ".join(sol.motivos_revisao or ["PDF inválido."]))
        return _sol_dict(sol)

    @app.get("/api/solicitacoes", **rota)
    def listar(status: str | None = None, limite: int = 200, db: Session = Depends(db_sessao)):
        q = db.query(Solicitacao)
        if status:
            q = q.filter_by(status=status)
        return [_sol_dict(s) for s in q.order_by(Solicitacao.id.desc()).limit(min(limite, 500))]

    @app.get("/api/solicitacoes/{sid}", **rota)
    def detalhe(sid: int, db: Session = Depends(db_sessao)):
        s = db.get(Solicitacao, sid)
        if not s:
            raise HTTPException(404, "Solicitação não encontrada.")
        acoes = db.query(Acao).filter_by(solicitacao_id=sid).order_by(Acao.id).all()
        trilha = db.query(Auditoria).filter_by(solicitacao_id=sid).order_by(Auditoria.id).all()
        return {**_sol_dict(s),
                "acoes": [{"ferramenta": a.ferramenta, "status": a.status, "ator": a.ator,
                           "decidido_por": a.decidido_por} for a in acoes],
                "auditoria": [{"quando": t.criado_em.isoformat(), "ator": t.ator, "evento": t.evento,
                               "detalhe": t.detalhe, "permitido": t.permitido} for t in trilha]}

    @app.post("/api/solicitacoes/{sid}/revisao", **rota)
    def revisar(sid: int, rev: Revisao, db: Session = Depends(db_sessao)):
        s = db.get(Solicitacao, sid)
        if not s:
            raise HTTPException(404, "Solicitação não encontrada.")
        if s.status in ("APROVADA", "REJEITADA"):
            raise HTTPException(409, "Solicitação já revisada.")
        if s.status in ("BLOQUEADO", "ERRO") and rev.decisao == "aprovar":
            raise HTTPException(409, "Documento bloqueado ou inválido não pode ser aprovado.")
        ator = f"humano:{rev.revisor}"
        aprovar = rev.decisao == "aprovar"
        tools.decidir_pendentes(db, s, rev.revisor, aprovar)
        if aprovar and rev.aprovar_reembolso:
            valor = (s.campos or {}).get("valor_brl")
            if s.categoria != "reembolso" or valor is None:
                raise HTTPException(422, "Reembolso exige categoria 'reembolso' e valor identificado.")
            tools.executar(db, s, "aprovar_reembolso", {"valor_brl": valor}, ator=ator)
        s.status = "APROVADA" if aprovar else "REJEITADA"
        s.revisor, s.revisado_em, s.nota_revisao = rev.revisor, agora(), rev.nota
        tools.auditar(db, s.id, ator, f"revisao:{s.status}", rev.nota or "")
        db.commit()
        return _sol_dict(s)

    @app.get("/api/relatorio", **rota)
    def relatorio(db: Session = Depends(db_sessao)):
        return gerar_relatorio(db)

    @app.get("/api/relatorio.md", response_class=PlainTextResponse, **rota)
    def relatorio_md(db: Session = Depends(db_sessao)):
        return para_markdown(gerar_relatorio(db))

    return app

