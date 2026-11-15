"""Automatic retraining: every 15 corrections, the model is trained again and swapped (made-up data)."""

import joblib
import pytest
from fastapi.testclient import TestClient

from api import config
from api.main import app
from api.services import retraining
from ml.retrain import CORRECTIONS_TO_RETRAIN
from ml.tests.test_retrain import _base
from ml.train import build_model

HEADER = "Data,Valor,Identificador,Descrição\n"
N = CORRECTIONS_TO_RETRAIN


@pytest.fixture
def with_base_csv(tmp_path, monkeypatch):
    """Base training CSV and a current .pkl (made up) instead of the real ones."""
    base = _base()
    path = tmp_path / "rotuladas.csv"
    base.to_csv(path, index=False)
    monkeypatch.setattr(config, "BASE_TRAINING_PATH", path)
    pkl = tmp_path / "modelo.pkl"
    joblib.dump(build_model().fit(base.drop(columns=["categoria"]), base["categoria"]), pkl)
    monkeypatch.setattr(config, "MODEL_PATH", pkl)
    return pkl


def _import_and_list(n):
    lines = "".join(f"{d:02d}/01/2024,-4.70,11111111-2222-4333-8444-{d:012d},Compra no débito - "
                    f"UNIVERSIDADE FICTICIA DO SUL\n" for d in range(1, n + 1))
    client = TestClient(app)
    assert client.post("/api/extratos", files={"arquivo": ("e.csv", (HEADER + lines).encode())}).status_code == 200
    return client, [t["id"] for t in client.get("/api/transacoes", params={"inicio": "2024-01-01"}).json()]


def _fix(client, ids, category="alimentacao_fora"):
    for i in ids:
        assert client.patch(f"/api/transacoes/{i}", json={"categoria": category}).status_code == 204


def test_correction_is_saved_before_checking_the_retraining(db):
    client, [i] = _import_and_list(1)
    _fix(client, [i])
    assert db.commits == 1 and db.trainings_ == []  # 1 correction: does not retrain yet


def test_retrains_on_the_15th_correction_and_swaps_the_model(db, with_base_csv):
    client, ids = _import_and_list(N + 2)
    before = with_base_csv.stat().st_mtime_ns
    _fix(client, ids[: N - 1])
    assert db.trainings_ == []
    _fix(client, ids[N - 1: N])  # the 15th
    [t] = db.trainings_
    assert t["status"] == "ok" and t["correcoes"] == N
    assert t["acerto_correcoes_antes"] == 0.0 and t["acerto_correcoes_depois"] == 100.0
    assert with_base_csv.stat().st_mtime_ns != before  # new .pkl in place
    assert with_base_csv.with_name("modelo.anterior.pkl").exists()  # and the previous one kept
    # the counter starts over: 2 more corrections do not trigger another retraining
    _fix(client, ids[N:])
    assert len(db.trainings_) == 1


def test_new_model_classifies_the_next_import(db, with_base_csv):
    client, ids = _import_and_list(N)
    assert {t["categoria"] for t in client.get("/api/transacoes", params={"inicio": "2024-01-01"}).json()} == {"compras"}
    _fix(client, ids)
    new = f"{HEADER}20/02/2024,-4.70,11111111-2222-4333-8444-999999999999,Compra no débito - UNIVERSIDADE FICTICIA DO SUL\n"
    [t] = client.post("/api/extratos", files={"arquivo": ("f.csv", new.encode())}).json()["transacoes"]
    assert (t["categoria"], t["origem_categoria"]) == ("alimentacao_fora", "modelo")


def test_correction_to_uncategorized_does_not_count(db, with_base_csv):
    client, ids = _import_and_list(N)
    _fix(client, ids, category=None)
    assert db.trainings_ == []


def test_without_base_csv_records_error_and_the_correction_stays_valid(db):
    client, ids = _import_and_list(N)
    _fix(client, ids)
    [t] = db.trainings_
    assert t["status"] == "erro" and t["mensagem"].startswith("FileNotFoundError")
    assert all(row["categoria"] == "alimentacao_fora" for row in db.rows)


def test_failure_in_the_check_does_not_get_in_the_way_of_the_correction(db, monkeypatch):
    client, [i] = _import_and_list(1)
    monkeypatch.setattr(db, "corrections_since_last_training", lambda: 1 / 0)
    _fix(client, [i])
    assert db.rows[0]["categoria"] == "alimentacao_fora"


def test_does_not_run_two_retrainings_together(db, with_base_csv):
    db.start_training()  # one "rodando"
    assert retraining.run_retraining() is None


def test_training_uses_only_anonymized_fields(db, with_base_csv, monkeypatch):
    client, ids = _import_and_list(N)
    seen = {}

    def spy(base, corrections, current_model=None):
        seen["columns"] = set(corrections.columns)
        raise ValueError("parar aqui")

    monkeypatch.setattr(retraining, "retrain", spy)
    _fix(client, ids)
    assert "original_cifrado" not in seen["columns"] and "contraparte_original" not in seen["columns"]


def test_after_an_error_does_not_retrain_on_every_correction(db):
    # no base CSV in the tests: the retraining on the 15th correction fails
    client, ids = _import_and_list(N + 3)
    _fix(client, ids[:N])
    assert [t["status"] for t in db.trainings_] == ["erro"]
    # before, each correction after an error triggered another retraining (which failed again)
    _fix(client, ids[N:])
    assert len(db.trainings_) == 1


def test_retraining_start_is_atomic(db, with_base_csv):
    """The database starts the retraining (start_training_if_free), not a "check and then save"."""
    assert db.start_training_if_free() is not None
    assert db.start_training_if_free() is None
    assert retraining.run_retraining() is None


# --- corrections in their own table: they survive the deletion of the statement ---

def _delete_the_statement(client):
    [statement] = client.get("/api/extratos").json()
    assert client.delete(f"/api/extratos/{statement['id']}").status_code == 204


def test_correction_survives_statement_deletion_and_counts_in_the_retraining(db, with_base_csv):
    client, ids = _import_and_list(N - 1)
    _fix(client, ids)
    _delete_the_statement(client)
    assert db.rows == [] and len(db.corrections_for_training()) == N - 1
    # a new statement and 1 correction complete the 15: the retraining also uses the ones from the deleted statement
    new = f"{HEADER}20/02/2024,-4.70,11111111-2222-4333-8444-999999999999,Compra no débito - UNIVERSIDADE FICTICIA DO SUL\n"
    assert client.post("/api/extratos", files={"arquivo": ("f.csv", new.encode())}).status_code == 200
    [t] = client.get("/api/transacoes", params={"inicio": "2024-01-01"}).json()
    _fix(client, [t["id"]])
    [training] = db.trainings_
    assert training["status"] == "ok" and training["correcoes"] == N


def test_reimporting_and_fixing_again_does_not_duplicate_the_correction(db):
    client, [i] = _import_and_list(1)
    _fix(client, [i])
    _delete_the_statement(client)
    client, [j] = _import_and_list(1)  # the same file again
    _fix(client, [j], category="transporte")
    [c] = db.corrections_for_training()
    assert c["categoria"] == "transporte"


def test_going_back_to_uncategorized_undoes_the_correction(db):
    client, [i] = _import_and_list(1)
    _fix(client, [i])
    _fix(client, [i], category=None)
    assert db.corrections_for_training() == []


def test_deleting_the_account_deletes_the_corrections(db):
    client, ids = _import_and_list(2)
    _fix(client, ids)
    assert client.delete("/api/conta").status_code == 204
    assert db.corrections_for_training() == []
