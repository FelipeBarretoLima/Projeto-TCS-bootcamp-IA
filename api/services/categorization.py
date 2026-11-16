"""Category of each transaction: inflows by rule, outflows by the classifier (ML).

    1. inflow (money received)  -> "receitas"                       origin "regra"
    2. outflow                  -> classifier ml/modelos/*.pkl      origin "modelo"

The fixed rules and the merchant map (ml.classes.by_rule, data/private) do not come in here:
they only produce the training labels (python -m ml.label). The model learned what they did.
Measured on the labeled CSV, outflows only: ~99% accuracy on an already seen merchant, 100% on PIX
to a person/fee/card bill and ~81% on a never seen merchant (cross-validation by store).

Without the .pkl, the outflows stay uncategorized.
"""

import logging
from pathlib import Path

import joblib
import pandas as pd

from statement.models import COLUMNS
from ml.classes import Category

from .. import config
from ..schemas import Transaction, UploadResult

log = logging.getLogger(__name__)

# path -> (modification time, model): reloads by itself if the .pkl is trained again
_model_cache: dict[Path, tuple[float, object]] = {}


def load_model(path: Path):
    """The classifier from the .pkl, or None if it does not exist or does not load."""
    try:
        modified = path.stat().st_mtime
    except FileNotFoundError:
        return None
    cached = _model_cache.get(path)
    if cached is not None and cached[0] == modified:
        return cached[1]
    try:
        model = joblib.load(path)
    except Exception:  # different scikit-learn version, corrupted file...
        log.exception("não foi possível carregar o classificador %s; seguindo sem ele", path)
        return None
    _model_cache[path] = (modified, model)
    return model


def _income_by_rule(t: Transaction) -> Transaction:
    if t.tipo == "entrada":
        return t.model_copy(update={"categoria": Category.INCOME.value, "origem_categoria": "regra"})
    return t


def _by_model(transactions: list[Transaction], model) -> list[Transaction]:
    """Classifies with the model the transactions still uncategorized (the outflows)."""
    pending = [i for i, t in enumerate(transactions) if t.categoria is None]
    if not pending:
        return transactions
    # the .pkl receives the parser CSV columns; id_usuario and data are ignored by the model
    rows = []
    for i in pending:
        t = transactions[i]
        row = t.model_dump(include=set(COLUMNS) - {"id_usuario"})
        row.update(id_usuario="", data=t.data.isoformat(), valor=float(t.valor))
        rows.append(row)
    predicted = model.predict(pd.DataFrame(rows, columns=list(COLUMNS)))
    result = list(transactions)
    for i, category in zip(pending, predicted):
        result[i] = transactions[i].model_copy(
            update={"categoria": str(category), "origem_categoria": "modelo"}
        )
    return result


def categorize(result: UploadResult) -> UploadResult:
    transactions = [_income_by_rule(t) for t in result.transacoes]
    model = load_model(config.MODEL_PATH)
    if model is not None:
        transactions = _by_model(transactions, model)
    else:
        log.warning("classificador ausente (%s): as saídas ficam sem categoria", config.MODEL_PATH)
    return result.model_copy(update={
        "transacoes": transactions,
        "sem_categoria": sum(t.categoria is None for t in transactions),
    })
