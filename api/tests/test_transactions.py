"""GET /api/transacoes: saved transactions of the logged-in user, with period and category filters."""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.routes.transactions import window_start
from api.tests.fakes import OTHER_USER, USER


def _t(day, category, amount="-10.00", month=1):
    return {"data": date(2024, month, day), "historico": "COMPRA", "contraparte": "LOJA", "valor": Decimal(amount),
            "tipo": "saida", "meio": "cartao_debito", "banco": "nubank", "categoria": category,
            "origem_categoria": "regra" if category else None}


@pytest.fixture
def with_transactions(db):
    db.save_statement(USER.id, nome_arquivo="jan.csv", hash_arquivo="a", parser="nubank_csv",
                      periodo_inicio=None, periodo_fim=None,
                      transactions=[_t(5, "mercado", "-50.00"), _t(10, "transporte", "-20.00"),
                                    _t(20, None, "-5.00"), _t(3, "mercado", "-30.00", month=2)])
    db.save_statement(OTHER_USER.id, nome_arquivo="outro.csv", hash_arquivo="b", parser="nubank_csv",
                      periodo_inicio=None, periodo_fim=None, transactions=[_t(7, "mercado", "-99.00")])
    return db


def _find(**params):
    return TestClient(app).get("/api/transacoes", params=params)


def test_without_filter_returns_all_of_the_user_from_the_most_recent(with_transactions):
    r = _find()
    assert r.status_code == 200
    assert [t["data"] for t in r.json()] == ["2024-02-03", "2024-01-20", "2024-01-10", "2024-01-05"]
    assert "-99.00" not in [t["valor"] for t in r.json()]  # nothing from the other user


def test_does_not_say_where_the_category_came_from(with_transactions):
    assert all("origem_categoria" not in t for t in _find().json())


def test_filters_by_inclusive_period(with_transactions):
    r = _find(inicio="2024-01-05", fim="2024-01-10")
    assert [t["data"] for t in r.json()] == ["2024-01-10", "2024-01-05"]


def test_filters_only_by_start_date(with_transactions):
    assert [t["data"] for t in _find(inicio="2024-02-01").json()] == ["2024-02-03"]


def test_filters_by_category(with_transactions):
    r = _find(categoria="mercado")
    assert [t["valor"] for t in r.json()] == ["-30.00", "-50.00"]


def test_filters_uncategorized(with_transactions):
    r = _find(categoria="sem_categoria")
    assert [(t["data"], t["categoria"]) for t in r.json()] == [("2024-01-20", None)]


def test_combines_period_and_category(with_transactions):
    r = _find(inicio="2024-01-01", fim="2024-01-31", categoria="mercado")
    assert [t["data"] for t in r.json()] == ["2024-01-05"]


def test_without_statements_returns_empty_list():
    assert _find().json() == []


def test_invalid_category_gives_400(with_transactions):
    assert _find(categoria="lazer").status_code == 400


def test_inverted_period_gives_400(with_transactions):
    assert _find(inicio="2024-02-01", fim="2024-01-01").status_code == 400


def test_badly_formatted_date_gives_422(with_transactions):
    assert _find(inicio="05/01/2024").status_code == 422


# --- period and default filter (last 6 months, ending in the month of the last transaction) ---

@pytest.mark.parametrize("last, expected", [
    (date(2024, 3, 15), date(2023, 10, 1)),   # crosses the year
    (date(2024, 6, 30), date(2024, 1, 1)),
    (date(2024, 12, 1), date(2024, 7, 1)),
    (date(2024, 1, 31), date(2023, 8, 1)),
])
def test_start_of_the_6_month_window(last, expected):
    assert window_start(last) == expected


def test_period_without_transactions():
    r = TestClient(app).get("/api/transacoes/periodo")
    assert r.status_code == 200
    assert r.json() == {"primeira": None, "ultima": None, "padrao_inicio": None, "padrao_fim": None}


def test_default_period_is_the_6_months_up_to_the_last_transaction(db):
    db.save_statement(USER.id, nome_arquivo="a.csv", hash_arquivo="a", parser="p", periodo_inicio=None,
                      periodo_fim=None, transactions=[_t(10, None, month=1), _t(20, None, month=12)])
    assert TestClient(app).get("/api/transacoes/periodo").json() == {
        "primeira": "2024-01-10", "ultima": "2024-12-20",
        "padrao_inicio": "2024-07-01", "padrao_fim": "2024-12-20"}


def test_short_period_starts_at_the_first_transaction(with_transactions):
    # transactions only in Jan and Feb/2024: the window would go back to Sep/2023, but the first transaction is on 05/01
    assert TestClient(app).get("/api/transacoes/periodo").json() == {
        "primeira": "2024-01-05", "ultima": "2024-02-03",
        "padrao_inicio": "2024-01-05", "padrao_fim": "2024-02-03"}


@pytest.mark.parametrize("transaction_id", [0, -1, 2**63])
def test_id_outside_the_database_range_answers_422_not_500(transaction_id):
    r = TestClient(app).patch(f"/api/transacoes/{transaction_id}", json={"categoria": "mercado"})
    assert r.status_code == 422
