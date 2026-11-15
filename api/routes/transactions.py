"""Transactions saved in the user's account (Extrato tab), with period and category filters."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response

from database.repository import Database
from ml.classes import Category

from .. import cipher
from ..auth import User, current_user
from ..dependencies import database
from ..schemas import NewCategory, SavedTransaction, TransactionPeriod
from ..services import retraining

router = APIRouter(tags=["transacoes"])

UNCATEGORIZED = "sem_categoria"
DEFAULT_MONTHS = 6
# the id is a bigint in the database: outside this range Postgres raised an error and the route answered 500
MAX_ID = 2**63 - 1


def window_start(last: date, months: int = DEFAULT_MONTHS) -> date:
    """1st day of the month that opens the N-month window ending in the month of `last`.

    Same rule as the dashboard (agent/queries.py): the window ends in the month of the most recent
    transaction, not in the current month. E.g.: last on 15/03/2024, 6 months -> 01/10/2023.
    """
    index = last.year * 12 + (last.month - 1) - (months - 1)
    return date(index // 12, index % 12 + 1, 1)


@router.get("/transacoes/periodo")
def period(
    user: Annotated[User, Depends(current_user)], db: Annotated[Database, Depends(database)]
) -> TransactionPeriod:
    first, last = db.transaction_period(user.id)
    if last is None:
        return TransactionPeriod(primeira=None, ultima=None, padrao_inicio=None, padrao_fim=None)
    return TransactionPeriod(primeira=first, ultima=last,
                             padrao_inicio=max(first, window_start(last)), padrao_fim=last)


@router.get("/transacoes")
def list_transactions(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Database, Depends(database)],
    start: Annotated[date | None, Query(alias="inicio", description="Data inicial (inclusiva), AAAA-MM-DD")] = None,
    end: Annotated[date | None, Query(alias="fim", description="Data final (inclusiva), AAAA-MM-DD")] = None,
    category: Annotated[str | None, Query(alias="categoria", description="Uma das categorias ou 'sem_categoria'")] = None,
) -> list[SavedTransaction]:
    if start and end and start > end:
        raise HTTPException(400, "a data inicial deve ser anterior ou igual à data final")
    valid = {c.value for c in Category}
    if category is not None and category != UNCATEGORIZED and category not in valid:
        raise HTTPException(400, "categoria inválida")
    rows = db.find_transactions(
        user.id,
        start=start,
        end=end,
        categoria=category if category in valid else None,
        uncategorized=category == UNCATEGORIZED,
    )
    try:
        return [_with_original(t) for t in rows]
    except cipher.InvalidKey as exc:
        raise HTTPException(500, str(exc)) from None


def _with_original(row: dict) -> SavedTransaction:
    """Decrypts the original only to return it to the owner; the encrypted text never leaves the API."""
    original = cipher.decrypt(row.pop("original_cifrado", None)) or {}
    return SavedTransaction(**row, historico_original=original.get("historico") or None,
                            contraparte_original=original.get("contraparte") or None)


@router.patch("/transacoes/{transacao_id}", status_code=204)
def set_category(
    transaction_id: Annotated[int, Path(alias="transacao_id", ge=1, le=MAX_ID)],
    new: NewCategory,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Database, Depends(database)],
) -> Response:
    """The user fixes the category (it applies to the dashboard and the assistant). None = uncategorized.

    The correction also becomes a training example: every 15 new ones, the model is retrained in the
    background (api/services/retraining.py).
    """
    if new.categoria is not None and new.categoria not in {c.value for c in Category}:
        raise HTTPException(400, "categoria inválida")
    if not db.set_category(user.id, transaction_id, new.categoria):
        raise HTTPException(404, "transação não encontrada")
    # save now: the retraining runs on another connection and needs to see this correction
    db.commit()
    retraining.trigger_if_needed(db)
    return Response(status_code=204)
