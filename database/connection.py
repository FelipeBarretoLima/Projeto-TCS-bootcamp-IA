"""Database connection pool (opened the first time the API needs it)."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg_pool import ConnectionPool

_pool: ConnectionPool | None = None
_pool_lock = threading.Lock()


class DatabaseNotConfigured(Exception):
    """DATABASE_URL is empty in .env."""


def _open_pool(url: str) -> ConnectionPool:
    # prepare_threshold=None: no prepared statements, which the Supabase pooler may not accept
    return ConnectionPool(url, min_size=1, max_size=5, open=True, timeout=15,
                          kwargs={"prepare_threshold": None, "connect_timeout": 10})


@contextmanager
def connect(url: str) -> Iterator[psycopg.Connection]:
    """A connection from the pool. Exits without error: commit. Exits with error: rollback (nothing half-done)."""
    global _pool
    if not url:
        raise DatabaseNotConfigured
    if _pool is None:
        with _pool_lock:
            # check again inside the lock: two simultaneous first requests used to create
            # two pools, and the connections of the one left behind were never closed
            if _pool is None:
                _pool = _open_pool(url)
    with _pool.connection() as con:
        yield con


def close_pool() -> None:
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.close()
            _pool = None
