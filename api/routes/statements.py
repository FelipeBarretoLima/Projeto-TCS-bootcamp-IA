import hashlib
import re
from datetime import date
from pathlib import PurePath
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Path, Response, UploadFile

from database.repository import Database, DuplicateStatement

from .. import cipher
from ..auth import User, current_user
from ..config import ACCEPTED_EXTENSIONS, DEFAULT_PSEUDONYM, MAX_SIZE
from ..dependencies import database
from ..schemas import ImportResult, SaveSummary, Transaction, UploadedStatement
from ..rate_limit import limit_import
from ..services.categorization import categorize
from ..services.extraction import OutputLeak, process_statement

router = APIRouter(tags=["extratos"])


def _date_or_none(text: str) -> date | None:
    try:
        return date.fromisoformat(text)
    except (TypeError, ValueError):
        return None


def _to_save(t: Transaction) -> dict:
    """What goes to the database: anonymized fields + the original only encrypted (never in plain text)."""
    row = t.model_dump(exclude={"historico_original", "contraparte_original"})
    if t.historico_original is not None or t.contraparte_original is not None:
        row["original_cifrado"] = cipher.encrypt(
            {"historico": t.historico_original or "", "contraparte": t.contraparte_original or ""})
    return row


# `def` (not `async def`): the extraction is heavy and blocking; FastAPI runs it in a separate thread
@router.post("/extratos", dependencies=[Depends(limit_import)])
def upload_statement(
    file: Annotated[UploadFile, File(alias="arquivo", description="Extrato em PDF ou CSV")],
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Database, Depends(database)],
    pseudonym: Annotated[str, Form(alias="usuario", description="Pseudônimo uNN")] = DEFAULT_PSEUDONYM,
) -> ImportResult:
    if not re.fullmatch(r"u\d{2}", pseudonym):
        raise HTTPException(400, "usuário deve ser 'u' + 2 dígitos (ex.: u07)")

    name = PurePath(file.filename or "")
    extension = name.suffix.lower()
    if extension not in ACCEPTED_EXTENSIONS:
        raise HTTPException(400, "formato não aceito: envie um arquivo .pdf ou .csv")

    content = file.file.read(MAX_SIZE + 1)
    if len(content) > MAX_SIZE:
        raise HTTPException(400, "arquivo maior que 10 MB")
    if not content:
        raise HTTPException(400, "arquivo vazio")

    try:
        result = process_statement(content, extension, pseudonym)
    except OutputLeak:
        raise HTTPException(
            422, "possível dado pessoal detectado na saída: nenhuma transação foi devolvida"
        ) from None

    result = categorize(result)

    summary = None
    if result.relatorio.status == "aceito" and result.transacoes:
        db.ensure_user(user.id, user.email, user.name)
        try:
            saved = db.save_statement(
                user.id,
                nome_arquivo=name.name[:200],
                hash_arquivo=hashlib.sha256(content).hexdigest(),
                parser=result.relatorio.parser,
                periodo_inicio=_date_or_none(result.relatorio.periodo_inicio),
                periodo_fim=_date_or_none(result.relatorio.periodo_fim),
                transactions=[_to_save(t) for t in result.transacoes],
            )
        except DuplicateStatement:
            raise HTTPException(409, "este arquivo já foi importado") from None
        except cipher.InvalidKey as exc:
            raise HTTPException(500, str(exc)) from None
        summary = SaveSummary(extrato_id=saved.statement_id, gravadas=saved.saved, repetidas=saved.duplicates)
    return ImportResult(**result.model_dump(), gravacao=summary)


@router.get("/extratos")
def list_statements(
    user: Annotated[User, Depends(current_user)], db: Annotated[Database, Depends(database)]
) -> list[UploadedStatement]:
    return [UploadedStatement(**e) for e in db.list_statements(user.id)]


@router.delete("/extratos/{extrato_id}", status_code=204)
def delete_statement(
    statement_id: Annotated[UUID, Path(alias="extrato_id")],
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Database, Depends(database)],
) -> Response:
    if not db.delete_statement(user.id, statement_id):
        raise HTTPException(404, "extrato não encontrado")
    return Response(status_code=204)
