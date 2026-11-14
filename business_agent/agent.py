"""Pipeline do agente: PDF -> guarda -> análise -> validação -> ações com permissão -> revisão humana.

Fluxo (cada passo é auditado):
  1. lê o PDF e calcula o hash (se já foi processado, devolve o existente: idempotente)
  2. GUARDA: PromptShield decide ALLOW / REVIEW / BLOCK sobre o texto
       BLOCK  -> para aqui: o conteúdo NEM chega ao provedor de análise
  3. provedor (regras ou LLM) devolve uma Analise validada
  4. decide se precisa de humano (confiança baixa, campos faltando, urgente, guarda em REVIEW)
  5. executa só o que a política permite; o resto vira proposta aguardando aprovação
"""
from __future__ import annotations

import hashlib
import time

from sqlalchemy.orm import Session

from . import tools
from .db import Solicitacao
from .guard import Guard
from .pdf_reader import PdfInvalido, extrair_texto
from .providers import Provider, ProviderError
from .schemas import Categoria, Prioridade

LIMIAR_CONFIANCA = 0.6

RESPOSTAS = {
    Categoria.REEMBOLSO: "Recebemos seu pedido de reembolso e ele está em análise. Retornaremos em até 5 dias úteis.",
    Categoria.SUPORTE: "Recebemos seu chamado técnico. Nossa equipe já está analisando e entrará em contato.",
    Categoria.COTACAO: "Obrigado pelo interesse. Nossa equipe comercial enviará a cotação em breve.",
    Categoria.RECLAMACAO: "Lamentamos o ocorrido. Sua reclamação foi registrada e será tratada com prioridade.",
    Categoria.CANCELAMENTO: "Recebemos sua solicitação de cancelamento. Um atendente confirmará os próximos passos.",
    Categoria.OUTROS: "Recebemos sua mensagem. Um atendente irá analisá-la e responder em breve.",
}


class Agente:
    def __init__(self, provider: Provider, guard: Guard):
        self.provider = provider
        self.guard = guard

    def processar(self, db: Session, nome_arquivo: str, conteudo: bytes) -> Solicitacao:
        inicio = time.perf_counter()
        sha = hashlib.sha256(conteudo).hexdigest()
        existente = db.query(Solicitacao).filter_by(sha256=sha).one_or_none()
        if existente:
            tools.auditar(db, existente.id, "agente", "duplicado", "PDF já processado; devolvendo o existente")
            db.commit()
            return existente

        sol = Solicitacao(arquivo=nome_arquivo[:255], sha256=sha, status="PROCESSADO", provedor=self.provider.nome)
        db.add(sol)
        db.flush()
        tools.auditar(db, sol.id, "agente", "recebido", f"{nome_arquivo} ({len(conteudo)} bytes)")

        motivos: list[str] = []
        try:
            texto = extrair_texto(conteudo)
        except PdfInvalido as e:
            return self._fechar(db, sol, inicio, "ERRO", [str(e)])

        # ---- 2. guarda de entrada ------------------------------------------------
        g = self.guard.verificar(texto) if texto else None
        if g:
            sol.guarda_decisao, sol.guarda_score = g.decision, g.score
            tools.auditar(db, sol.id, "guarda", f"promptshield:{g.decision}", f"score={g.score} erro={g.erro}")
            if g.decision == "BLOCK":
                return self._fechar(db, sol, inicio, "BLOQUEADO", ["possivel_prompt_injection"])
            if g.decision == "REVIEW":
                motivos.append("guarda_suspeita" if not g.erro else "guarda_indisponivel")
        if not texto:
            return self._fechar(db, sol, inicio, "PENDENTE_REVISAO", ["sem_texto_extraivel(provavel_pdf_escaneado)"])

        # ---- 3. análise ----------------------------------------------------------
        try:
            a = self.provider.analisar(texto)
        except ProviderError as e:
            return self._fechar(db, sol, inicio, "PENDENTE_REVISAO", [f"falha_na_analise:{e}"])
        sol.categoria, sol.prioridade = a.categoria.value, a.prioridade.value
        sol.resumo, sol.campos = a.resumo, a.campos.model_dump()
        sol.justificativa, sol.confianca = a.justificativa, a.confianca
        tools.auditar(db, sol.id, "agente", "analise", f"{a.categoria.value}/{a.prioridade.value} conf={a.confianca}")

        # ---- 4. precisa de humano? ----------------------------------------------
        if a.confianca < LIMIAR_CONFIANCA:
            motivos.append("confianca_baixa")
        if a.campos.cliente is None:
            motivos.append("cliente_nao_identificado")
        if a.prioridade == Prioridade.URGENTE:
            motivos.append("prioridade_urgente")

        # ---- 5. ações (a política decide o que é executado) ---------------------
        tools.executar(db, sol, "registrar_ticket",
                       {"titulo": f"[{a.categoria.value}] {a.campos.cliente or 'cliente não identificado'}",
                        "prioridade": a.prioridade.value})
        tools.executar(db, sol, "gerar_rascunho_resposta", {"texto": RESPOSTAS[a.categoria]})
        if a.campos.email:
            tools.executar(db, sol, "enviar_resposta_cliente", {"destinatario": a.campos.email})
        return self._fechar(db, sol, inicio, "PENDENTE_REVISAO" if motivos else "PROCESSADO", motivos)

    @staticmethod
    def _fechar(db: Session, sol: Solicitacao, inicio: float, status: str, motivos: list[str]) -> Solicitacao:
        sol.status, sol.motivos_revisao = status, motivos
        sol.tempo_ms = round((time.perf_counter() - inicio) * 1000, 2)
        tools.auditar(db, sol.id, "agente", f"status:{status}", "; ".join(motivos))
        db.commit()
        return sol
