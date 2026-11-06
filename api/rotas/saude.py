from fastapi import APIRouter

from ..esquemas import Saude

router = APIRouter(tags=["saúde"])


@router.get("/saude")
def saude() -> Saude:
    return Saude(status="ok")
