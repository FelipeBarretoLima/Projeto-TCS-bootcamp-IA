"""Common route dependencies: database and assistant (replaced by fake versions in the tests)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager

from fastapi import HTTPException

from database.connection import DatabaseNotConfigured, connect
from database.repository import Database

from . import config

OpenDatabase = Callable[[], AbstractContextManager[Database]]


@contextmanager
def short_transaction() -> Iterator[Database]:
    """A transaction open only for the duration of the `with` block: on error, nothing is saved."""
    try:
        with connect(config.DATABASE_URL) as con:
            yield Database(con)
    except DatabaseNotConfigured:
        raise HTTPException(503, "banco não configurado: preencha DATABASE_URL no .env") from None


def database() -> Iterator[Database]:
    """One transaction per request (the connection stays held until the response goes out)."""
    with short_transaction() as db:
        yield db


def open_database() -> OpenDatabase:
    """For slow routes (the chat): the route opens short transactions when it needs them, instead of
    holding a pool connection (there are only 5) during the LLM call. In the tests it is replaced by
    one that returns the fake database."""
    return short_transaction


_model = None


def assistant_model():
    """The Gemini models: primary + fallbacks (created once)."""
    global _model
    if not config.GEMINI_API_KEY:
        raise HTTPException(503, "assistente não configurado: preencha GEMINI_API_KEY no .env")
    if _model is None:
        from agent.assistant import gemini_models

        _model = gemini_models(config.GEMINI_API_KEY, config.GEMINI_MODEL, config.GEMINI_FALLBACK_MODELS,
                               config.GEMINI_TIMEOUT)
    return _model
