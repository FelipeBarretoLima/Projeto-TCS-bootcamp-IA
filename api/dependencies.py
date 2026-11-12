"""Dependências comuns das rotas: banco e assistente (trocadas por versões falsas nos testes)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager

from fastapi import HTTPException

from database.connection import BancoNaoConfigurado, conexao
from database.repository import Banco

from . import config

AbreBanco = Callable[[], AbstractContextManager[Banco]]


@contextmanager
def transacao_curta() -> Iterator[Banco]:
    """Uma transação aberta só pelo tempo do bloco `with`: deu erro, nada fica gravado."""
    try:
        with conexao(config.DATABASE_URL) as con:
            yield Banco(con)
    except BancoNaoConfigurado:
        raise HTTPException(503, "banco não configurado: preencha DATABASE_URL no .env") from None


def banco() -> Iterator[Banco]:
    """Uma transação por requisição (a conexão fica presa até a resposta sair)."""
    with transacao_curta() as db:
        yield db


def abre_banco() -> AbreBanco:
    """Para rotas lentas (o chat): a rota abre transações curtas quando precisa, em vez de prender
    uma conexão do pool (são só 5) durante a chamada ao LLM. Nos testes é trocada por uma que
    devolve o banco falso."""
    return transacao_curta


_modelo = None


def modelo_do_assistente():
    """Os modelos do Gemini: principal + reservas (criados uma vez)."""
    global _modelo
    if not config.GEMINI_API_KEY:
        raise HTTPException(503, "assistente não configurado: preencha GEMINI_API_KEY no .env")
    if _modelo is None:
        from agent.assistant import modelos_gemini

        _modelo = modelos_gemini(config.GEMINI_API_KEY, config.GEMINI_MODEL, config.GEMINI_MODELOS_RESERVA,
                                 config.GEMINI_TIMEOUT)
    return _modelo
