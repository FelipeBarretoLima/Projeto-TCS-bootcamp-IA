"""Retraining with the category corrections made by users (no database: receives everything ready).

Training = base labeled CSV (rules + map, `python -m ml.label`) + users' corrections:
  - each correction weighs CORRECTION_WEIGHT examples (a single one already changes the model);
  - the correction replaces the automatic label of the same merchant in the base CSV (counterparty
    base name), except PESSOA_FISICA and an empty counterparty: correcting a PIX to a friend does not
    change every PIX to people;
  - corrections that disagree on the same merchant: the most recent one wins.
Corrections arrive only with the anonymized fields of the parser contract (never the original text).

Fetching the corrections from the database, swapping the .pkl and recording the history is done
by api/services/retraining.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from statement.merchants import base_name
from statement.models import COLUMNS, INDIVIDUAL_PERSON

from .train import TARGET, build_model

CORRECTION_WEIGHT = 5
CORRECTIONS_TO_RETRAIN = 15
_GENERIC = ("", INDIVIDUAL_PERSON)


@dataclass(frozen=True)
class RetrainResult:
    model: object
    correcoes: int
    linhas_treino: int
    acerto_correcoes_antes: float | None  # % of the corrections the previous model already got right
    acerto_correcoes_depois: float        # % of the corrections the new model gets right
    acerto_base_depois: float             # % of the base CSV (with the labels already replaced)


def _pct(hits: np.ndarray) -> float:
    return round(100 * float(np.mean(hits)), 2) if len(hits) else 0.0


def build_training_set(base: pd.DataFrame, correcoes: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray]:
    """Base CSV with the labels replaced + the corrections, and the weight of each row.

    `correcoes`: parser columns + `categoria` + `corrigida_em` (to decide the most recent one).
    """
    base = base.copy()
    corr = correcoes.sort_values("corrigida_em") if "corrigida_em" in correcoes else correcoes
    corr_key = corr["contraparte"].map(base_name)
    specific = ~corr_key.isin(_GENERIC)
    # the same merchant corrected more than once: the last correction wins
    by_store = dict(zip(corr_key[specific], corr.loc[specific, TARGET]))
    if by_store:
        base_key = base["contraparte"].map(base_name)
        to_replace = base_key.isin(list(by_store))
        base.loc[to_replace, TARGET] = base_key[to_replace].map(by_store)
    training = pd.concat([base[[*COLUMNS, TARGET]], corr[[*COLUMNS, TARGET]]], ignore_index=True)
    weights = np.concatenate([np.ones(len(base)), np.full(len(corr), CORRECTION_WEIGHT, dtype=float)])
    return training, weights


def retrain(base: pd.DataFrame, correcoes: pd.DataFrame, current_model=None) -> RetrainResult:
    """Trains the new model. `current_model` (optional) is only used to measure the "before"."""
    if base.empty:
        raise ValueError("CSV base de treino vazio")
    if (base[TARGET] == "").any() or (correcoes[TARGET] == "").any():
        raise ValueError("há linhas sem categoria no treino")
    training, weights = build_training_set(base, correcoes)
    X, y = training.drop(columns=[TARGET]), training[TARGET]
    model = build_model().fit(X, y, clf__sample_weight=weights)

    Xc, yc = correcoes[list(COLUMNS)], correcoes[TARGET].to_numpy()
    before = _pct(current_model.predict(Xc) == yc) if current_model is not None and len(correcoes) else None
    n_base = len(training) - len(correcoes)
    return RetrainResult(
        model=model,
        correcoes=len(correcoes),
        linhas_treino=len(training),
        acerto_correcoes_antes=before,
        acerto_correcoes_depois=_pct(model.predict(Xc) == yc) if len(correcoes) else 0.0,
        acerto_base_depois=_pct(model.predict(X.iloc[:n_base]) == y.iloc[:n_base].to_numpy()),
    )


def read_base(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, keep_default_na=False)
    if TARGET not in df.columns:
        raise ValueError(f"o CSV base não tem a coluna {TARGET!r} (gere com python -m ml.label)")
    return df
