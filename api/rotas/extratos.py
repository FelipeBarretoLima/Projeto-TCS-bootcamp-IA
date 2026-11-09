import hashlib
import re
from datetime import date
from pathlib import PurePath
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile

from banco.repositorio import Banco, ExtratoRepetido

from ..autenticacao import Usuario, usuario_atual
from ..config import EXTENSOES_ACEITAS, TAMANHO_MAXIMO, USUARIO_PADRAO
from ..dependencias import banco
from ..esquemas import ExtratoEnviado, Gravacao, ResultadoImportacao
from ..servicos.categorizacao import MapaInvalido, categoriza
from ..servicos.extracao import VazamentoNaSaida, processa_extrato

router = APIRouter(tags=["extratos"])


def _data_ou_none(texto: str) -> date | None:
    try:
        return date.fromisoformat(texto)
    except (TypeError, ValueError):
        return None


# `def` (não `async def`): a extração é pesada e bloqueante; o FastAPI roda num thread à parte
@router.post("/extratos")
def envia_extrato(
    arquivo: Annotated[UploadFile, File(description="Extrato em PDF ou CSV")],
    usuario: Annotated[Usuario, Depends(usuario_atual)],
    db: Annotated[Banco, Depends(banco)],
    pseudonimo: Annotated[str, Form(alias="usuario", description="Pseudônimo uNN")] = USUARIO_PADRAO,
) -> ResultadoImportacao:
    if not re.fullmatch(r"u\d{2}", pseudonimo):
        raise HTTPException(400, "usuário deve ser 'u' + 2 dígitos (ex.: u07)")

    nome = PurePath(arquivo.filename or "")
    extensao = nome.suffix.lower()
    if extensao not in EXTENSOES_ACEITAS:
        raise HTTPException(400, "formato não aceito: envie um arquivo .pdf ou .csv")

    conteudo = arquivo.file.read(TAMANHO_MAXIMO + 1)
    if len(conteudo) > TAMANHO_MAXIMO:
        raise HTTPException(400, "arquivo maior que 10 MB")
    if not conteudo:
        raise HTTPException(400, "arquivo vazio")

    try:
        resultado = processa_extrato(conteudo, extensao, pseudonimo)
    except VazamentoNaSaida:
        raise HTTPException(
            422, "possível dado pessoal detectado na saída: nenhuma transação foi devolvida"
        ) from None

    try:
        resultado = categoriza(resultado)
    except MapaInvalido as exc:
        raise HTTPException(500, f"mapa de estabelecimentos inválido: {exc}") from None

    gravacao = None
    if resultado.relatorio.status == "aceito" and resultado.transacoes:
        db.garante_usuario(usuario.id, usuario.email, usuario.nome)
        try:
            g = db.grava_extrato(
                usuario.id,
                nome_arquivo=nome.name[:200],
                hash_arquivo=hashlib.sha256(conteudo).hexdigest(),
                parser=resultado.relatorio.parser,
                periodo_inicio=_data_ou_none(resultado.relatorio.periodo_inicio),
                periodo_fim=_data_ou_none(resultado.relatorio.periodo_fim),
                transacoes=[t.model_dump() for t in resultado.transacoes],
            )
        except ExtratoRepetido:
            raise HTTPException(409, "este arquivo já foi importado") from None
        gravacao = Gravacao(extrato_id=g.extrato_id, gravadas=g.gravadas, repetidas=g.repetidas)
    return ResultadoImportacao(**resultado.model_dump(), gravacao=gravacao)


@router.get("/extratos")
def lista_extratos(
    usuario: Annotated[Usuario, Depends(usuario_atual)], db: Annotated[Banco, Depends(banco)]
) -> list[ExtratoEnviado]:
    return [ExtratoEnviado(**e) for e in db.lista_extratos(usuario.id)]


@router.delete("/extratos/{extrato_id}", status_code=204)
def apaga_extrato(
    extrato_id: UUID, usuario: Annotated[Usuario, Depends(usuario_atual)], db: Annotated[Banco, Depends(banco)]
) -> Response:
    if not db.apaga_extrato(usuario.id, extrato_id):
        raise HTTPException(404, "extrato não encontrado")
    return Response(status_code=204)
