"""Automatic retraining: every 15 new category corrections, the model is trained again.

    python -m api.retrain     forces a retraining now (without waiting for the 15)

Flow (in a separate thread, with its own connection: the user does not wait):
  1. records the start in treinos_modelo ("rodando": another retraining does not start alongside);
  2. reads the corrections of all users (anonymized fields only) and the base training CSV;
  3. trains (ml/retrain.py: a correction weighs 5 and replaces the store's automatic label);
  4. swaps the .pkl at once (the previous one stays in svm_tfidf.anterior.pkl): the API loads the new
     one by itself on the next import (categorization.load_model looks at the file date);
  5. records the result (accuracy before/after) or the error.
The new model always goes in (user's decision on 2026-11-11); the accuracies are only recorded.
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Any

import joblib
import pandas as pd

from database.connection import connect
from database.repository import Database
from statement.models import COLUMNS
from ml.retrain import CORRECTIONS_TO_RETRAIN, read_base, retrain

from .. import config
from .categorization import load_model

log = logging.getLogger(__name__)

_one_at_a_time = threading.Lock()


@contextmanager
def _open_database() -> Iterator[Database]:
    with connect(config.DATABASE_URL) as con:
        yield Database(con)


# replaced in the tests by a fake database
open_database: Callable[[], AbstractContextManager[Database]] = _open_database


def needs_retraining(db: Database) -> bool:
    return db.corrections_since_last_training() >= CORRECTIONS_TO_RETRAIN and not db.training_running()


def _to_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=[*COLUMNS, "categoria", "corrigida_em"])
    df["id_usuario"] = ""
    df["data"] = df["data"].astype(str)
    df["valor"] = df["valor"].astype(float)
    return df


def _save(model) -> None:
    """Writes next to it and swaps at once: whoever loads the .pkl never gets a half-written file."""
    target = config.MODEL_PATH
    new = target.with_name(target.stem + ".novo.pkl")
    joblib.dump(model, new)
    if target.exists():
        shutil.copy2(target, target.with_name(target.stem + ".anterior.pkl"))
    os.replace(new, target)


def run_retraining() -> dict[str, Any] | None:
    """Runs a retraining now. None if another one is already running. Returns what was recorded."""
    if not _one_at_a_time.acquire(blocking=False):
        return None
    try:
        with open_database() as db:
            training_id = db.start_training_if_free()  # atomic: another process may be retraining
            if training_id is None:
                return None
            corrections = _to_frame(db.corrections_for_training())
        # the record keys are columns of public.treinos_modelo (Database.finish_training)
        try:
            r = retrain(read_base(config.BASE_TRAINING_PATH), corrections, load_model(config.MODEL_PATH))
            _save(r.model)
            record = dict(status="ok", correcoes=r.correcoes, linhas_treino=r.linhas_treino,
                          acerto_correcoes_antes=r.acerto_correcoes_antes,
                          acerto_correcoes_depois=r.acerto_correcoes_depois,
                          acerto_base_depois=r.acerto_base_depois)
        except (OSError, ValueError) as exc:  # missing base CSV, no category... (our own messages)
            record = dict(status="erro", correcoes=len(corrections), mensagem=f"{type(exc).__name__}: {exc}")
        except Exception as exc:  # another failure: only the type (the message may carry data values)
            log.exception("retreino falhou")
            record = dict(status="erro", correcoes=len(corrections), mensagem=type(exc).__name__)
        with open_database() as db:
            db.finish_training(training_id, **record)
        log.info("retreino %s: %s", training_id, record)
        return record
    finally:
        _one_at_a_time.release()


def _in_background(target: Callable[[], object]) -> None:
    threading.Thread(target=target, name="retreino", daemon=True).start()


# replaced in the tests to run right away
start_in_background: Callable[[Callable[[], object]], None] = _in_background


def trigger_if_needed(db: Database) -> bool:
    """Called after saving a correction (already committed to the database). True if it triggered."""
    try:
        if not needs_retraining(db):
            return False
    except Exception:  # the retraining can never get in the way of the user's correction
        log.exception("não foi possível verificar se precisa retreinar")
        return False
    start_in_background(run_retraining)
    return True
