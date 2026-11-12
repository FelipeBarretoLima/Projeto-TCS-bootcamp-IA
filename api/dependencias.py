"""Dependências comuns das rotas: banco e assistente (trocadas por versões falsas nos testes)."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import HTTPException

from banco.conexao import BancoNaoConfigurado, conexao
from banco.repositorio import Banco

from . import config


def banco() -> Iterator[Banco]:
    """Uma transação por requisição: se a rota der erro, nada fica gravado."""
    try:
        with conexao(config.DATABASE_URL) as con:
            yield Banco(con)
    except BancoNaoConfigurado:
        raise HTTPException(503, "banco não configurado: preencha DATABASE_URL no .env") from None


_modelo = None


def modelo_do_assistente():
    """Os modelos do Gemini: principal + reservas (criados uma vez)."""
    global _modelo
    if not config.GEMINI_API_KEY:
        raise HTTPException(503, "assistente não configurado: preencha GEMINI_API_KEY no .env")
    if _modelo is None:
        from agente.assistente import modelos_gemini

        _modelo = modelos_gemini(config.GEMINI_API_KEY, config.GEMINI_MODEL, config.GEMINI_MODELOS_RESERVA,
                                 config.GEMINI_TIMEOUT)
    return _modelo
