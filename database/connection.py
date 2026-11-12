"""Pool de conexões com o banco (aberto na primeira vez que a API precisa dele)."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg_pool import ConnectionPool

_pool: ConnectionPool | None = None
_trava_pool = threading.Lock()


class BancoNaoConfigurado(Exception):
    """DATABASE_URL vazio no .env."""


def _abre(url: str) -> ConnectionPool:
    # prepare_threshold=None: sem prepared statements, que o pooler do Supabase pode não aceitar
    return ConnectionPool(url, min_size=1, max_size=5, open=True, timeout=15,
                          kwargs={"prepare_threshold": None, "connect_timeout": 10})


@contextmanager
def conexao(url: str) -> Iterator[psycopg.Connection]:
    """Uma conexão do pool. Sai sem erro: commit. Sai com erro: rollback (nada fica pela metade)."""
    global _pool
    if not url:
        raise BancoNaoConfigurado
    if _pool is None:
        with _trava_pool:
            # confere de novo dentro da trava: duas primeiras requisições ao mesmo tempo criavam
            # dois pools, e as conexões do que ficava para trás nunca eram fechadas
            if _pool is None:
                _pool = _abre(url)
    with _pool.connection() as con:
        yield con


def fecha() -> None:
    global _pool
    with _trava_pool:
        if _pool is not None:
            _pool.close()
            _pool = None
