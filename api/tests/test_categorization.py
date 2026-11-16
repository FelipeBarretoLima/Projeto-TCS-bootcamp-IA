"""Category in the API: inflows = income (rule), outflows = classifier. Made-up data."""

import csv
from datetime import date
from decimal import Decimal

import joblib
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from api import config
from api.schemas import Report, Transaction, UploadResult
from api.main import app
from api.services import categorization
from api.services.categorization import categorize
from statement.models import COLUMNS, INDIVIDUAL_PERSON
from ml import label
from ml.train import build_model

HEADER = "Data,Valor,Identificador,Descrição\n"
U1 = "11111111-2222-4333-8444-555555555555"


def _write_map(folder, rows):
    with open(folder / label.REVIEWED_FILE, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=label.MAP_COLUMNS, lineterminator="\n")
        w.writeheader()
        for row in rows:
            w.writerow({c: row.get(c, "") for c in label.MAP_COLUMNS})


def _transaction(method, kind, history, counterparty, amount="-10.00"):
    return Transaction(data=date(2024, 1, 2), historico=history, contraparte=counterparty,
                       valor=Decimal(amount), tipo=kind, meio=method, banco="banco_teste")


def _result(*transactions):
    report = Report(status="aceito", motivo="", parser="p", periodo_inicio="", periodo_fim="",
                    linhas_extraidas=0, linhas_gravadas=0, linhas_revisar=0,
                    linhas_duplicadas=0, linhas_omitidas=0, reconciliacao="ok")
    return UploadResult(relatorio=report, transacoes=list(transactions))


CASES = [
    _transaction("tarifa", "saida", "TARIFA", ""),
    _transaction("pix", "entrada", "PIX RECEBIDO", INDIVIDUAL_PERSON, "50.00"),
    _transaction("pix", "saida", "PIX ENVIADO", INDIVIDUAL_PERSON),
    _transaction("boleto", "saida", "PAGAMENTO DE BOLETO", ""),
    _transaction("cartao_debito", "saida", "COMPRA", "PADARIA MODELO"),
    _transaction("cartao_credito", "saida", "COMPRA", "LOJA INVENTADA"),
    _transaction("pix", "saida", "PIX ENVIADO", "EMPRESA FICTICIA LTDA"),
]


def test_inflow_is_income_by_rule_and_outflow_without_model_stays_uncategorized():
    fee, pix_received, *outflows = categorize(_result(*CASES)).transacoes
    assert (pix_received.categoria, pix_received.origem_categoria) == ("receitas", "regra")
    # without the .pkl, no outflow has a category: not even the fee, which used to be a fixed rule
    assert all((t.categoria, t.origem_categoria) == (None, None) for t in [fee, *outflows])


def test_counts_uncategorized():
    assert categorize(_result(*CASES)).sem_categoria == 6  # only the inflow has a category


def test_merchant_map_is_not_used_in_the_api(private_dir):
    # the map only produces labels for training; in the API the model decides the outflows
    _write_map(private_dir, [{"contraparte": "PADARIA MODELO", "classe": "mercado"}])
    csv_ = (f"{HEADER}02/01/2024,-12.50,{U1},Compra no débito - PADARIA MODELO\n").encode()
    r = TestClient(app).post("/api/extratos", files={"arquivo": ("e.csv", csv_)})
    assert r.status_code == 200
    [t] = r.json()["transacoes"]
    assert (t["categoria"], t["origem_categoria"]) == (None, None)
    assert r.json()["sem_categoria"] == 1


def test_invalid_map_does_not_break_the_import(private_dir):
    _write_map(private_dir, [{"contraparte": "PADARIA MODELO", "classe": "nao_existe"}])
    csv_ = (f"{HEADER}02/01/2024,-12.50,{U1},Compra no débito - PADARIA MODELO\n").encode()
    assert TestClient(app).post("/api/extratos", files={"arquivo": ("e.csv", csv_)}).status_code == 200


# --- classifier (all outflows) ---

class _FakeModel:
    """Always returns the same class and keeps what it received."""

    def __init__(self, label_):
        self.label, self.received = label_, None

    def predict(self, df):
        self.received = df
        return [self.label] * len(df)


def test_model_classifies_every_outflow_and_never_the_inflows(private_dir, monkeypatch):
    _write_map(private_dir, [{"contraparte": "PADARIA MODELO", "classe": "mercado"}])  # ignored
    fake = _FakeModel("compras")
    monkeypatch.setattr(categorization, "load_model", lambda path: fake)
    result = categorize(_result(*CASES))
    fee, pix_received, pix_sent, bill, bakery, store, company = result.transacoes
    assert (pix_received.categoria, pix_received.origem_categoria) == ("receitas", "regra")
    for t in (fee, pix_sent, bill, bakery, store, company):
        assert (t.categoria, t.origem_categoria) == ("compras", "modelo")
    assert result.sem_categoria == 0
    # the model receives only the outflows, with the parser CSV columns and the numeric amount
    assert list(fake.received.columns) == list(COLUMNS)
    assert list(fake.received["tipo"]) == ["saida"] * 6
    assert list(fake.received["contraparte"]) == [
        "", INDIVIDUAL_PERSON, "", "PADARIA MODELO", "LOJA INVENTADA", "EMPRESA FICTICIA LTDA"]
    assert fake.received["valor"].dtype == float


def test_only_inflows_the_model_is_not_called(monkeypatch):
    fake = _FakeModel("compras")
    monkeypatch.setattr(categorization, "load_model", lambda path: fake)
    categorize(_result(CASES[1]))
    assert fake.received is None


def test_load_model_missing_or_corrupted(tmp_path):
    assert categorization.load_model(tmp_path / "nao_existe.pkl") is None
    broken = tmp_path / "quebrado.pkl"
    broken.write_bytes(b"isto nao e um pickle")
    assert categorization.load_model(broken) is None


def _train_pkl(path):
    """A real model (the same pipeline as ml.train), with made-up data."""
    stores = {"mercado": "SUPERMERCADO FICTICIO", "transporte": "POSTO INVENTADO",
              "alimentacao_fora": "PIZZARIA IMAGINARIA"}
    rows = [dict(id_usuario="u01", data="2024-01-02", historico="COMPRA", contraparte=f"{name} {i}",
                 valor=-10.0 - i, tipo="saida", meio="cartao_credito", banco="banco_teste", categoria=cat)
            for cat, name in stores.items() for i in range(10)]
    df = pd.DataFrame(rows)
    joblib.dump(build_model().fit(df.drop(columns=["categoria"]), df["categoria"]), path)


def test_upload_with_real_model(tmp_path, monkeypatch):
    path = tmp_path / "modelo.pkl"
    _train_pkl(path)
    monkeypatch.setattr(config, "MODEL_PATH", path)
    csv_ = (f"{HEADER}02/01/2024,-12.50,{U1},Compra no débito - PIZZARIA IMAGINARIA\n").encode()
    r = TestClient(app).post("/api/extratos", files={"arquivo": ("e.csv", csv_)})
    assert r.status_code == 200
    [t] = r.json()["transacoes"]
    assert (t["categoria"], t["origem_categoria"]) == ("alimentacao_fora", "modelo")
    assert r.json()["sem_categoria"] == 0
