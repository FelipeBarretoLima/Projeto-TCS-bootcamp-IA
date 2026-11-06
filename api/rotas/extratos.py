import re
from pathlib import PurePath
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from ..config import EXTENSOES_ACEITAS, TAMANHO_MAXIMO, USUARIO_PADRAO
from ..esquemas import ResultadoUpload
from ..servicos.categorizacao import MapaInvalido, categoriza
from ..servicos.extracao import VazamentoNaSaida, processa_extrato

router = APIRouter(tags=["extratos"])


# `def` (não `async def`): a extração é pesada e bloqueante; o FastAPI roda num thread à parte
@router.post("/extratos")
def envia_extrato(
    arquivo: Annotated[UploadFile, File(description="Extrato em PDF ou CSV")],
    usuario: Annotated[str, Form(description="Pseudônimo uNN")] = USUARIO_PADRAO,
) -> ResultadoUpload:
    if not re.fullmatch(r"u\d{2}", usuario):
        raise HTTPException(400, "usuário deve ser 'u' + 2 dígitos (ex.: u07)")

    extensao = PurePath(arquivo.filename or "").suffix.lower()
    if extensao not in EXTENSOES_ACEITAS:
        raise HTTPException(400, "formato não aceito: envie um arquivo .pdf ou .csv")

    conteudo = arquivo.file.read(TAMANHO_MAXIMO + 1)
    if len(conteudo) > TAMANHO_MAXIMO:
        raise HTTPException(400, "arquivo maior que 10 MB")
    if not conteudo:
        raise HTTPException(400, "arquivo vazio")

    try:
        resultado = processa_extrato(conteudo, extensao, usuario)
    except VazamentoNaSaida:
        raise HTTPException(
            422, "possível dado pessoal detectado na saída: nenhuma transação foi devolvida"
        ) from None

    try:
        return categoriza(resultado)
    except MapaInvalido as exc:
        raise HTTPException(500, f"mapa de estabelecimentos inválido: {exc}") from None
