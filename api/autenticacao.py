"""Quem está chamando a API: confere o token do Supabase Auth que o frontend manda.

O login acontece no frontend (supabase-js). A cada chamada, o frontend manda
`Authorization: Bearer <access_token>` e a API pergunta ao Supabase de quem é o token
(GET /auth/v1/user). A resposta fica em cache por 60 s para não consultar a cada clique.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

import httpx
from fastapi import Header, HTTPException

from . import config

_CACHE_SEGUNDOS = 60
_cache: dict[str, tuple[float, "Usuario"]] = {}


@dataclass(frozen=True)
class Usuario:
    id: UUID
    email: str
    nome: str


def _consulta_supabase(token: str) -> Usuario | None:
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
    return Usuario(UUID(d["id"]), d.get("email") or "", (d.get("user_metadata") or {}).get("nome", ""))


def usuario_atual(authorization: Annotated[str | None, Header()] = None) -> Usuario:
    """Dependência das rotas que precisam de login. 401 se faltar ou não valer o token."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "faça login para continuar")
    token = authorization[7:].strip()
    agora = time.monotonic()
    em_cache = _cache.get(token)
    if em_cache and em_cache[0] > agora:
        return em_cache[1]
    usuario = _consulta_supabase(token)
    if usuario is None:
        raise HTTPException(401, "sessão expirada: faça login de novo")
    if len(_cache) > 1000:
        _cache.clear()
    _cache[token] = (agora + _CACHE_SEGUNDOS, usuario)
    return usuario
