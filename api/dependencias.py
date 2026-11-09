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
    """O chat model do Gemini (criado uma vez)."""
    global _modelo
    if not config.GEMINI_API_KEY:
        raise HTTPException(503, "assistente não configurado: preencha GEMINI_API_KEY no .env")
    if _modelo is None:
        from agente.assistente import modelo_gemini

        _modelo = modelo_gemini(config.GEMINI_API_KEY, config.GEMINI_MODEL)
    return _modelo
