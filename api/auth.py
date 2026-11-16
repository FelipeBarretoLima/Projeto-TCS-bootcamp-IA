"""Who is calling the API: checks the Supabase Auth token the frontend sends.

The login happens in the frontend (supabase-js). On every call, the frontend sends
`Authorization: Bearer <access_token>` and the API asks Supabase whose token it is
(GET /auth/v1/user). The answer is cached for 60 s so it does not query on every click.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

import httpx
from fastapi import Header, HTTPException

from . import config

_CACHE_SECONDS = 60
_cache: dict[str, tuple[float, "User"]] = {}


@dataclass(frozen=True)
class User:
    id: UUID
    email: str
    name: str


def _query_supabase(token: str) -> User | None:
    if not (config.SUPABASE_URL and config.SUPABASE_PUBLISHABLE_KEY):
        raise HTTPException(503, "login não configurado: preencha SUPABASE_PUBLISHABLE_KEY no .env")
    try:
        r = httpx.get(f"{config.SUPABASE_URL}/auth/v1/user", timeout=10,
                      headers={"apikey": config.SUPABASE_PUBLISHABLE_KEY, "Authorization": f"Bearer {token}"})
    except httpx.HTTPError:
        raise HTTPException(503, "não foi possível falar com o serviço de login") from None
    if r.status_code != 200:
        return None
    d = r.json()
    return User(UUID(d["id"]), d.get("email") or "", (d.get("user_metadata") or {}).get("nome", ""))


def forget_token(authorization: str | None) -> None:
    """Logout: the token stops being valid here right away, without waiting for the cache to expire."""
    if authorization and authorization.lower().startswith("bearer "):
        _cache.pop(authorization[7:].strip(), None)


def forget_user(user_id: UUID) -> None:
    """Deleted account: all its tokens (other devices and tabs) stop being valid here right away.

    Without this, a token from another device stayed in the cache for up to 60 s, and the next
    request tried to recreate the profile of a login that no longer exists (error 500).
    """
    for token in [t for t, (_, u) in list(_cache.items()) if u.id == user_id]:
        _cache.pop(token, None)


def current_user(authorization: Annotated[str | None, Header()] = None) -> User:
    """Dependency of the routes that need login. 401 if the token is missing or not valid."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "faça login para continuar")
    token = authorization[7:].strip()
    now = time.monotonic()
    cached = _cache.get(token)
    if cached and cached[0] > now:
        return cached[1]
    user = _query_supabase(token)
    if user is None:
        raise HTTPException(401, "sessão expirada: faça login de novo")
    if len(_cache) > 1000:
        _cache.clear()
    _cache[token] = (now + _CACHE_SECONDS, user)
    return user
