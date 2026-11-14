"""Ferramentas do agente + POLÍTICA DE PERMISSÕES.

Ideia central (a que mais vale numa entrevista):
    "A segurança do agente não depende de o modelo se comportar bem."

Mesmo que um PDF consiga enganar o classificador E o LLM, o agente só consegue chamar o que a
política permite. Ações sensíveis têm 3 níveis:
    PERMITIDO        - o agente executa sozinho (efeito interno e reversível)
    EXIGE_APROVACAO  - o agente só PROPÕE; um humano precisa aprovar (efeito externo)
    NEGADO           - o agente nunca executa; só um humano (ação financeira)
Toda tentativa, permitida ou não, entra na auditoria.
"""
from __future__ import annotations

from enum import StrEnum

from sqlalchemy.orm import Session

from .db import Acao, Auditoria, Outbox, Reembolso, Solicitacao, Ticket, agora


class Permissao(StrEnum):
    PERMITIDO = "permitido"
    EXIGE_APROVACAO = "exige_aprovacao"
    NEGADO = "negado"


POLITICA_AGENTE: dict[str, Permissao] = {
    "registrar_ticket": Permissao.PERMITIDO,
    "gerar_rascunho_resposta": Permissao.PERMITIDO,
    "enviar_resposta_cliente": Permissao.EXIGE_APROVACAO,
    "aprovar_reembolso": Permissao.NEGADO,
}
FERRAMENTAS_SO_HUMANO = {"aprovar_reembolso"}


class FerramentaDesconhecida(ValueError):
    pass


def _auditar(db: Session, sol_id: int | None, ator: str, evento: str, detalhe: str = "", permitido: bool = True):
    db.add(Auditoria(solicitacao_id=sol_id, ator=ator, evento=evento, detalhe=detalhe, permitido=permitido))


# ------------------------------------------------------------- efeitos (simulados)
def _efeito(db: Session, sol: Solicitacao, ferramenta: str, args: dict, ator: str) -> None:
    if ferramenta == "registrar_ticket":
        db.add(Ticket(solicitacao_id=sol.id, titulo=args["titulo"][:200], prioridade=args["prioridade"]))
    elif ferramenta == "gerar_rascunho_resposta":
        sol.rascunho_resposta = args["texto"]
    elif ferramenta == "enviar_resposta_cliente":
        db.add(Outbox(solicitacao_id=sol.id, destinatario=args["destinatario"], corpo=sol.rascunho_resposta or ""))
    elif ferramenta == "aprovar_reembolso":
        db.add(Reembolso(solicitacao_id=sol.id, valor_brl=args["valor_brl"], aprovado_por=ator))
    else:
        raise FerramentaDesconhecida(ferramenta)


def executar(db: Session, sol: Solicitacao, ferramenta: str, args: dict, ator: str = "agente") -> Acao:
    """Único ponto de entrada para ações. Aplica a política ANTES de qualquer efeito."""
    if ferramenta not in POLITICA_AGENTE:
        raise FerramentaDesconhecida(ferramenta)
    eh_agente = ator == "agente"
    permissao = POLITICA_AGENTE[ferramenta] if eh_agente else Permissao.PERMITIDO

    if eh_agente and permissao == Permissao.NEGADO:
        acao = Acao(solicitacao_id=sol.id, ferramenta=ferramenta, argumentos=args, status="NEGADA", ator=ator)
        db.add(acao)
        _auditar(db, sol.id, ator, f"tool:{ferramenta}", "NEGADA pela política", permitido=False)
        db.flush()
        return acao
    if eh_agente and permissao == Permissao.EXIGE_APROVACAO:
        acao = Acao(solicitacao_id=sol.id, ferramenta=ferramenta, argumentos=args, status="PENDENTE_APROVACAO",
                    ator=ator)
        db.add(acao)
        _auditar(db, sol.id, ator, f"tool:{ferramenta}", "proposta; aguardando aprovação humana")
        db.flush()
        return acao

    _efeito(db, sol, ferramenta, args, ator)
    acao = Acao(solicitacao_id=sol.id, ferramenta=ferramenta, argumentos=args, status="EXECUTADA", ator=ator)
    db.add(acao)
    _auditar(db, sol.id, ator, f"tool:{ferramenta}", "executada")
    db.flush()
    return acao


def decidir_pendentes(db: Session, sol: Solicitacao, revisor: str, aprovar: bool) -> int:
    """Humano aprova ou rejeita as ações que o agente apenas propôs. Devolve quantas foram decididas."""
    pendentes = db.query(Acao).filter_by(solicitacao_id=sol.id, status="PENDENTE_APROVACAO").all()
    for acao in pendentes:
        acao.decidido_por = f"humano:{revisor}"
        if aprovar:
            _efeito(db, sol, acao.ferramenta, acao.argumentos, f"humano:{revisor}")
            acao.status = "EXECUTADA"
        else:
            acao.status = "REJEITADA"
        acao.criado_em = acao.criado_em or agora()
        _auditar(db, sol.id, f"humano:{revisor}", f"tool:{acao.ferramenta}", acao.status)
    return len(pendentes)


auditar = _auditar
