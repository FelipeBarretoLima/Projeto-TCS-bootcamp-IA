from typing import Annotated

from fastapi import APIRouter, Header, Response

from .. import config
from ..auth import forget_token
from ..schemas import Health, PublicConfig

router = APIRouter(tags=["saúde"])


@router.delete("/sessao", status_code=204)
def end_session(authorization: Annotated[str | None, Header()] = None) -> Response:
    """Called on logout: the API forgets the token right away (Supabase ends the session)."""
    forget_token(authorization)
    return Response(status_code=204)


@router.get("/saude")
def health() -> Health:
    return Health(status="ok")


@router.get("/config")
def public_config() -> PublicConfig:
    """What the frontend needs for the login. Public data only: the publishable key is made to live
    in the browser (what protects the data is the login + RLS). The secret key never leaves here."""
    return PublicConfig(supabase_url=config.SUPABASE_URL,
                        supabase_publishable_key=config.SUPABASE_PUBLISHABLE_KEY)
