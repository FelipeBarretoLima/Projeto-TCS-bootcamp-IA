from fastapi import APIRouter

from .. import config
from ..esquemas import ConfigPublica, Saude

router = APIRouter(tags=["saúde"])


@router.get("/saude")
def saude() -> Saude:
    return Saude(status="ok")


@router.get("/config")
def config_publica() -> ConfigPublica:
    """O que o frontend precisa para o login. Só dados públicos: a chave publishable é feita para
    ficar no navegador (o que protege os dados é o login + RLS). A chave secreta nunca sai daqui."""
    return ConfigPublica(supabase_url=config.SUPABASE_URL,
                         supabase_publishable_key=config.SUPABASE_PUBLISHABLE_KEY)
