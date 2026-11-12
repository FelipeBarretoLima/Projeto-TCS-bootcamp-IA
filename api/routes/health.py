from typing import Annotated

from fastapi import APIRouter, Header, Response

from .. import config
from ..auth import esquece_token
from ..schemas import ConfigPublica, Saude

router = APIRouter(tags=["saúde"])


@router.delete("/sessao", status_code=204)
def encerra_sessao(authorization: Annotated[str | None, Header()] = None) -> Response:
    """Chamada no logout: a API esquece o token na hora (o Supabase encerra a sessão)."""
    esquece_token(authorization)
    return Response(status_code=204)


@router.get("/saude")
def saude() -> Saude:
    return Saude(status="ok")


@router.get("/config")
def config_publica() -> ConfigPublica:
    """O que o frontend precisa para o login. Só dados públicos: a chave publishable é feita para
    ficar no navegador (o que protege os dados é o login + RLS). A chave secreta nunca sai daqui."""
    return ConfigPublica(supabase_url=config.SUPABASE_URL,
                         supabase_publishable_key=config.SUPABASE_PUBLISHABLE_KEY)
