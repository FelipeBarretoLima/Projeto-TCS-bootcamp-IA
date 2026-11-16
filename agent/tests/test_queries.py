"""Assistant queries with made-up transactions."""

from datetime import date

import pytest

from agent import queries as q


def _t(day, amount, kind="saida", category="mercado", counterparty="LOJA FICTICIA", method="cartao_debito"):
    return {"data": day, "valor": amount, "tipo": kind, "categoria": category, "contraparte": counterparty,
            "meio": method, "banco": "banco_teste"}


@pytest.fixture
def df():
    return q.to_dataframe([
        _t(date(2024, 1, 10), 5000, "entrada", "receitas", "", "salario"),
        _t(date(2024, 1, 11), -300, category="mercado"),
        _t(date(2024, 1, 12), -80, category="alimentacao_fora", counterparty="PIZZARIA X"),
        _t(date(2024, 1, 20), -1500, category="financeiro", method="pagamento_fatura"),  # not an expense
        _t(date(2024, 3, 5), 5000, "entrada", "receitas", "", "salario"),
        _t(date(2024, 3, 6), -120, category="alimentacao_fora", counterparty="PIZZARIA X"),
        _t(date(2024, 3, 7), -40, category="alimentacao_fora", counterparty="LANCHE Y"),
        _t(date(2024, 3, 8), -900, category="compras", counterparty="LOJA Z"),
        _t(date(2024, 3, 9), -50, category=None, counterparty="DESCONHECIDA"),
        _t(date(2024, 3, 10), 30, "entrada", "financeiro", "", "estorno"),  # not income
    ])


def test_window_ends_in_the_most_recent_month_and_includes_empty_months(df):
    r = q.monthly_spending(df, 3, "alimentacao_fora")
    assert r.data["por_mes"] == {"jan/24": 80.0, "fev/24": 0.0, "mar/24": 160.0}
    assert r.data["total"] == 240.0 and r.data["periodo"] == "jan/24 a mar/24"
    assert r.chart["rotulos"] == ["jan/24", "fev/24", "mar/24"]


def test_financeiro_is_not_an_expense_and_uncategorized_is(df):
    r = q.monthly_spending(df, 3)
    assert r.data["por_mes"]["jan/24"] == 380.0      # without the 1500 of the card bill
    assert r.data["por_mes"]["mar/24"] == 1110.0     # includes the 50 without category


def test_spending_by_category_sorted_with_percentage(df):
    r = q.spending_by_category(df, 1)
    cats = r.data["categorias"]
    assert [x["categoria"] for x in cats] == ["compras", "alimentacao_fora", "sem_categoria"]
    assert r.data["total_gasto"] == 1110.0 and cats[0]["percentual"] == 81.08
    # pie: one slice per category, in the same order, with the totals
    assert r.chart["tipo"] == "pizza"
    assert r.chart["rotulos"] == ["Compras", "Alimentação fora", "Sem categoria"]
    assert r.chart["series"][0]["valores"] == [x["total"] for x in cats]


def test_income_vs_expenses_and_balance(df):
    r = q.income_vs_expenses(df, 3)
    assert r.data["por_mes"]["mar/24"] == {"receitas": 5000.0, "despesas": 1110.0, "saldo": 3890.0}
    assert [s["nome"] for s in r.chart["series"]] == ["Receitas", "Despesas"]
    e = q.balance_evolution(df, 3)
    assert e.data["saldo_por_mes"] == {"jan/24": 4620.0, "fev/24": 0.0, "mar/24": 3890.0}
    assert e.data["saldo_acumulado"] == 8510.0


def test_largest_expenses_and_by_merchant(df):
    m = q.largest_expenses(df, 3, 2)
    assert [(x["estabelecimento"], x["valor"]) for x in m.data["maiores"]] == [
        ("LOJA Z", 900.0), ("LOJA FICTICIA", 300.0)]
    e = q.spending_by_merchant(df, 3, category="alimentacao_fora")
    assert e.data["estabelecimentos"][0] == {"estabelecimento": "PIZZARIA X", "total": 200.0, "compras": 2}


def test_month_summary(df):
    r = q.month_summary(df, 2024, 1)
    assert (r.data["receitas"], r.data["despesas"], r.data["saldo"]) == (5000.0, 380.0, 4620.0)
    assert r.chart["tipo"] == "pizza"
    assert q.month_summary(df).data["mes"] == "mar/24"


def test_no_data_and_invalid_category(df):
    empty = q.to_dataframe([])
    assert q.monthly_spending(empty).data["sem_dados"] is True
    assert q.dashboard(empty)["tem_dados"] is False
    with pytest.raises(ValueError, match="categoria inválida"):
        q.monthly_spending(df, 3, "lazer")


def test_months_out_of_bounds_are_adjusted(df):
    assert len(q.monthly_spending(df, 0).chart["rotulos"]) == 1
    assert len(q.monthly_spending(df, 500).chart["rotulos"]) == q.MAX_MONTHS


# --- explicit period (start/end) ---

@pytest.fixture
def years():
    """Transactions from 2022 to 2024, like a long statement (the most recent month is Dec/24)."""
    return q.to_dataframe([
        _t(date(2022, 3, 10), -100, category="mercado"),
        _t(date(2023, 6, 10), -200, category="mercado"),
        _t(date(2024, 1, 10), -300, category="transporte", counterparty="POSTO X"),
        _t(date(2024, 12, 10), -400, category="mercado"),
        _t(date(2024, 12, 15), 2000, "entrada", "receitas", "", "salario"),
    ])


def test_specific_year_outside_the_last_months(years):
    r = q.monthly_spending(years, start="2023-01", end="2023-12")
    assert r.data["periodo"] == "jan/23 a dez/23" and r.data["total"] == 200.0
    assert len(r.chart["rotulos"]) == 12 and "aviso" not in r.data


def test_only_start_goes_up_to_the_most_recent_month(years):
    r = q.monthly_spending(years, start="2024-01")
    assert r.data["periodo"] == "jan/24 a dez/24" and r.data["total"] == 700.0


def test_only_end_uses_the_n_months_ending_in_it(years):
    r = q.monthly_spending(years, 3, end="2022-04")
    assert r.data["periodo"] == "fev/22 a abr/22" and r.data["total"] == 100.0


def test_every_query_accepts_the_period(years):
    assert q.spending_by_category(years, start="2022-01", end="2022-12").data["total_gasto"] == 100.0
    assert q.income_vs_expenses(years, start="2024-12", end="2024-12").data["saldo"] == 1600.0
    assert q.balance_evolution(years, start="2024-01", end="2024-12").data["saldo_acumulado"] == 1300.0
    assert q.largest_expenses(years, start="2023-01", end="2023-12").data["maiores"][0]["valor"] == 200.0
    assert q.spending_by_merchant(years, start="2024-01", end="2024-01").data["estabelecimentos"] == [
        {"estabelecimento": "POSTO X", "total": 300.0, "compras": 1}]


def test_period_without_statement_warns_instead_of_just_giving_zero(years):
    r = q.monthly_spending(years, start="2021-01", end="2021-12")
    assert r.data["total"] == 0.0 and r.data["sem_extrato_no_periodo"] is True
    assert "10/03/2022 a 15/12/2024" in r.data["aviso"]
    partial = q.monthly_spending(years, start="2021-12", end="2022-03")
    assert "sem_extrato_no_periodo" not in partial.data and "Parte do período" in partial.data["aviso"]
    assert "aviso" in q.balance_evolution(years, start="2025-01", end="2025-02").data


@pytest.mark.parametrize("start, end, error", [
    ("2024", None, "de inválido"),
    ("2024-13", None, "de inválido"),
    ("01/2024", None, "de inválido"),
    ("2024-05", "2024-02", "período inválido"),
    ("2019-01", "2024-12", "período longo demais"),
])
def test_invalid_period(years, start, end, error):
    with pytest.raises(ValueError, match=error):
        q.monthly_spending(years, start=start, end=end)


# --- summary month and refunds ---

def test_summary_with_only_the_month_uses_the_most_recent_year_with_that_month(df):
    # data up to Mar/24: "January" is Jan/24 and "December" is Dec/23 (not the most recent month)
    assert q.month_summary(df, None, 1).data["mes"] == "jan/24"
    assert q.month_summary(df, None, 1).data["despesas"] == 380.0
    assert q.month_summary(df, None, 12).data["mes"] == "dez/23"
    assert q.month_summary(df, 2024, None).data["mes"] == "mar/24"


def test_summary_with_invalid_month_returns_error_without_exception(df):
    assert "erro" in q.month_summary(df, 2024, 13).data


def test_refund_offsets_the_purchase_at_the_same_merchant():
    # every inflow is categorized as income (api/services/categorization.py), the refund too
    df = q.to_dataframe([
        _t(date(2024, 3, 1), -100, category="compras", counterparty="LOJA Z"),
        _t(date(2024, 3, 2), -30, category="transporte", counterparty="UBER"),
        _t(date(2024, 3, 5), 100, "entrada", "receitas", "LOJA Z", "estorno"),
        _t(date(2024, 3, 6), 15, "entrada", "receitas", "SEM COMPRA", "estorno"),  # no purchase: it is income
    ])
    assert q.monthly_spending(df, 1).data["total"] == 30.0
    # the LOJA Z refund already offset the purchase: it does not count again as income (only the 15 without purchase)
    assert q.income_vs_expenses(df, 1).data["por_mes"]["mar/24"] == {
        "receitas": 15.0, "despesas": 30.0, "saldo": -15.0}
    assert (q.month_summary(df).data["receitas"], q.dashboard(df)["receitas"]) == (15.0, 15.0)
    assert [x["categoria"] for x in q.spending_by_category(df, 1).data["categorias"]] == ["transporte"]
    assert q.month_summary(df).data["despesas"] == 30.0
    assert q.spending_by_merchant(df, 1).data["estabelecimentos"] == [
        {"estabelecimento": "UBER", "total": 30.0, "compras": 1}]
    # the purchase is still one of the largest purchases of the period
    assert q.largest_expenses(df, 1).data["maiores"][0]["valor"] == 100.0


def test_refund_in_a_month_without_the_purchase_does_not_make_the_month_negative():
    df = q.to_dataframe([
        _t(date(2024, 2, 1), -100, category="compras", counterparty="LOJA Z"),
        _t(date(2024, 3, 5), 100, "entrada", "receitas", "LOJA Z", "estorno"),
    ])
    assert q.monthly_spending(df, 2).data["por_mes"] == {"fev/24": 100.0, "mar/24": 0.0}
    assert q.income_vs_expenses(df, 1).data["total_despesas"] == 0.0
    # the March summary also sees the February purchase: the refund does not become income in the month
    assert q.month_summary(df, 2024, 3).data["receitas"] == 0.0
