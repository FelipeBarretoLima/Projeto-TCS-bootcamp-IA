"""Fixed assistant queries: transactions -> numbers + chart. The LLM only picks which one to call.

All the math is done here (pandas), never by the LLM. Each function returns a `Result`:
    data     what goes to the LLM to write the answer (totals only, never the list of transactions,
             except `largest_expenses`, which returns the N largest)
    chart    what the frontend draws (None = text only)

Definitions (the same in the dashboard and in the chat):
    expense  outflow that is not `financeiro` (paying the card bill, investing or transferring between
             one's own accounts is not spending: the spending is already in the card purchases)
    income   inflow in the `receitas` category
    "last N months" ends in the month of the user's most recent transaction, not in the current
    month: whoever sent statements up to October sees June-October, not an empty November.
    explicit period: `start` and `end` ("YYYY-MM", inclusive) replace the "last N months" with a
    fixed range (e.g. the year 2024 = start="2024-01", end="2024-12"). Only `start`: up to the most
    recent month. Only `end`: the N months ending in it. (For the LLM they are called `de` and `ate`.)

Chart format (the frontend draws it with Recharts):
    {"tipo": "barras" | "barras_horizontais" | "linha" | "pizza", "titulo": str,
     "rotulos": [str], "series": [{"nome": str, "valores": [float]}], "formato": "moeda"}
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
import re
from typing import Any

import pandas as pd

CATEGORIES = ("mercado", "alimentacao_fora", "transporte", "compras", "contas_servicos",
              "transferencia_pessoa", "receitas", "financeiro")
CATEGORY_NAMES = {
    "mercado": "Mercado", "alimentacao_fora": "Alimentação fora", "transporte": "Transporte",
    "compras": "Compras", "contas_servicos": "Contas e serviços",
    "transferencia_pessoa": "Transferência p/ pessoa", "receitas": "Receitas",
    "financeiro": "Financeiro", "sem_categoria": "Sem categoria",
}
_MONTHS = ("jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez")
MAX_MONTHS = 60  # 5 years: a long statement (e.g. Sicoob 2022-2026) fits whole


@dataclass
class Result:
    data: dict[str, Any]
    chart: dict[str, Any] | None = field(default=None)


# --- preparation ---

def to_dataframe(transactions: Iterable[Mapping[str, Any]]) -> pd.DataFrame:
    """Database rows (or rows of the parser CSV) -> DataFrame with the right types."""
    df = pd.DataFrame(list(transactions), columns=["data", "contraparte", "valor", "tipo", "meio", "banco", "categoria"])
    df["data"] = pd.to_datetime(df["data"])
    df["valor"] = pd.to_numeric(df["valor"]).astype(float)
    df["categoria"] = df["categoria"].fillna("").replace("", "sem_categoria")
    df["contraparte"] = df["contraparte"].fillna("")
    df["mes"] = df["data"].dt.to_period("M")
    return df


def _purchases(df: pd.DataFrame) -> pd.DataFrame:
    """Outflows that are spending, with the `gasto` column (positive)."""
    d = df[(df["tipo"] == "saida") & (df["categoria"] != "financeiro")].copy()
    d["gasto"] = d["valor"].abs()
    return d


def _matched_refunds(df: pd.DataFrame, purchases: pd.DataFrame | None = None) -> pd.DataFrame:
    """Refunds that give back a purchase: same merchant, purchase on the same day or before.

    Each one gets the category of the most recent purchase and a negative `gasto` (it offsets the
    purchase). The index is the same as `df`, so `_income` knows which ones to remove.
    """
    purchases = _purchases(df) if purchases is None else purchases
    refunds = df[(df["tipo"] == "entrada") & (df["meio"] == "estorno") & (df["contraparte"] != "")].copy()
    if refunds.empty or purchases.empty:
        return refunds.iloc[0:0].assign(gasto=pd.Series(dtype=float))
    ordered = purchases.sort_values("data")

    def purchase_category(e: pd.Series) -> str | None:
        before = ordered[(ordered["contraparte"] == e["contraparte"]) & (ordered["data"] <= e["data"])]
        return before["categoria"].iloc[-1] if not before.empty else None

    refunds["categoria"] = refunds.apply(purchase_category, axis=1)
    refunds = refunds[refunds["categoria"].notna()]
    return refunds.assign(gasto=-refunds["valor"].abs())


def _expenses(df: pd.DataFrame, with_refunds: bool = True) -> pd.DataFrame:
    """Outflows that are spending (`gasto` column, positive).

    With `with_refunds`, the purchase refunds also come in, with a negative `gasto`: the refunded
    purchase no longer counts as spending. A refund without a matching purchase does not come in
    here (it stays as income, see `_income`).
    """
    d = _purchases(df)
    if not with_refunds:
        return d
    refunds = _matched_refunds(df, d)
    return pd.concat([d, refunds]) if not refunds.empty else d


def _non_negative(series: pd.Series) -> pd.Series:
    """A refund in a month without the purchase can make the total negative: show zero."""
    return series.clip(lower=0.0)


def _income(df: pd.DataFrame) -> pd.DataFrame:
    """Inflows in the `receitas` category, minus the refunds that already offset a purchase in
    `_expenses` (every inflow is categorized as income: without this, the refund would count twice)."""
    r = df[(df["tipo"] == "entrada") & (df["categoria"] == "receitas")]
    return r.drop(index=_matched_refunds(df).index, errors="ignore")


def _parse_month(text: str, field_name: str) -> pd.Period:
    """"2024-03" -> Period("2024-03"). ValueError with a clear message if it comes in another format."""
    m = re.fullmatch(r"\s*(\d{4})-(\d{1,2})\s*", str(text))
    if not m or not 1 <= int(m[2]) <= 12:
        raise ValueError(f"{field_name} inválido: {text!r}. Use o formato AAAA-MM (ex.: 2024-01).")
    return pd.Period(year=int(m[1]), month=int(m[2]), freq="M")


def _window(df: pd.DataFrame, months: int, start: str | None = None, end: str | None = None) -> list[pd.Period]:
    """The queried months: the N ending in the most recent month, or the `start`..`end` range."""
    last = _parse_month(end, "ate") if end else df["mes"].max()
    if start:
        first = _parse_month(start, "de")
        if first > last:
            raise ValueError(f"período inválido: 'de' ({start}) é depois de 'ate' ({_label(last)}).")
        n = (last - first).n + 1
        if n > MAX_MONTHS:
            raise ValueError(f"período longo demais ({n} meses): o máximo é {MAX_MONTHS} meses por consulta.")
    else:
        n = max(1, min(int(months), MAX_MONTHS))
    return [last - i for i in range(n - 1, -1, -1)]


def _coverage(df: pd.DataFrame, window: list[pd.Period]) -> dict[str, Any]:
    """Warns when part of the requested period has no statement (so the LLM does not read zero as "did not spend")."""
    first, last = df["mes"].min(), df["mes"].max()
    if window[0] >= first and window[-1] <= last:
        return {}
    since, until = df["data"].min().strftime("%d/%m/%Y"), df["data"].max().strftime("%d/%m/%Y")
    if window[-1] < first or window[0] > last:
        return {"sem_extrato_no_periodo": True,
                "aviso": f"Não há extrato neste período. Os extratos enviados vão de {since} a {until}."}
    return {"aviso": f"Parte do período não tem extrato (os extratos enviados vão de {since} a {until}); "
                     "os meses sem extrato aparecem como zero."}


def _label(p: pd.Period) -> str:
    return f"{_MONTHS[p.month - 1]}/{str(p.year)[2:]}"


def _period_label(window: list[pd.Period]) -> str:
    return _label(window[0]) if len(window) == 1 else f"{_label(window[0])} a {_label(window[-1])}"


def _r(x: float) -> float:
    return round(float(x), 2)


def _empty() -> Result:
    return Result({"sem_dados": True, "aviso": "O usuário ainda não enviou nenhum extrato."})


def _validate_category(category: str | None) -> str | None:
    if category is None or category == "":
        return None
    if category not in CATEGORIES:
        raise ValueError(f"categoria inválida: {category!r}. Use uma de: {', '.join(CATEGORIES)}")
    return category


# --- queries ---

def available_period(df: pd.DataFrame) -> Result:
    if df.empty:
        return _empty()
    return Result({
        "primeira_data": df["data"].min().date().isoformat(),
        "ultima_data": df["data"].max().date().isoformat(),
        "transacoes": int(len(df)),
        "bancos": sorted(df["banco"].dropna().unique().tolist()),
    })


def monthly_spending(df: pd.DataFrame, months: int = 6, category: str | None = None,
                     start: str | None = None, end: str | None = None) -> Result:
    """Total spent in each month (in one category or in all of them).

    The "receitas" category is income, not spending: for it, the month total comes from the inflows
    (the same as the dashboard), otherwise "quanto recebi em 2025?" through this tool gave zero.
    """
    category = _validate_category(category)
    if df.empty:
        return _empty()
    window = _window(df, months, start, end)
    if category == "receitas":
        per_month = _income(df).groupby("mes")["valor"].sum().reindex(window, fill_value=0.0)
    else:
        d = _expenses(df)
        if category:
            d = d[d["categoria"] == category]
        per_month = _non_negative(d.groupby("mes")["gasto"].sum().reindex(window, fill_value=0.0))
    name = CATEGORY_NAMES[category] if category else "Gastos"
    values = [_r(v) for v in per_month]
    return Result(
        {"categoria": category or "todas", "periodo": _period_label(window),
         "por_mes": dict(zip(map(_label, window), values)), "total": _r(sum(values)),
         "media_mensal": _r(sum(values) / len(values)), **_coverage(df, window)},
        {"tipo": "barras", "titulo": f"{name} por mês ({_period_label(window)})", "rotulos": [_label(p) for p in window],
         "series": [{"nome": name, "valores": values}], "formato": "moeda"})


def spending_by_category(df: pd.DataFrame, months: int = 1, start: str | None = None,
                         end: str | None = None) -> Result:
    """How much was spent in each category in the period ("where did I spend the most?")."""
    if df.empty:
        return _empty()
    window = _window(df, months, start, end)
    d = _expenses(df)
    d = d[d["mes"].isin(window)]
    per_category = d.groupby("categoria")["gasto"].sum().sort_values(ascending=False)
    per_category = per_category[per_category > 0]
    total = float(per_category.sum())
    items = [{"categoria": c, "nome": CATEGORY_NAMES.get(c, c), "total": _r(v),
              "percentual": _r(100 * v / total) if total else 0.0} for c, v in per_category.items()]
    return Result(
        {"periodo": _period_label(window), "total_gasto": _r(total), "categorias": items, **_coverage(df, window)},
        # pie: shows how the total splits across the categories (the tooltip shows the %)
        {"tipo": "pizza", "titulo": f"Gastos por categoria ({_period_label(window)})",
         "rotulos": [i["nome"] for i in items], "series": [{"nome": "Gasto", "valores": [i["total"] for i in items]}],
         "formato": "moeda"})


def income_vs_expenses(df: pd.DataFrame, months: int = 6, start: str | None = None,
                       end: str | None = None) -> Result:
    if df.empty:
        return _empty()
    window = _window(df, months, start, end)
    inc = _income(df).groupby("mes")["valor"].sum().reindex(window, fill_value=0.0)
    exp = _non_negative(_expenses(df).groupby("mes")["gasto"].sum().reindex(window, fill_value=0.0))
    labels = [_label(p) for p in window]
    return Result(
        {"periodo": _period_label(window),
         "por_mes": {r: {"receitas": _r(a), "despesas": _r(b), "saldo": _r(a - b)}
                     for r, a, b in zip(labels, inc, exp)},
         "total_receitas": _r(inc.sum()), "total_despesas": _r(exp.sum()), "saldo": _r(inc.sum() - exp.sum()),
         **_coverage(df, window)},
        {"tipo": "barras", "titulo": f"Receitas x despesas ({_period_label(window)})", "rotulos": labels,
         "series": [{"nome": "Receitas", "valores": [_r(v) for v in inc]},
                    {"nome": "Despesas", "valores": [_r(v) for v in exp]}], "formato": "moeda"})


def balance_evolution(df: pd.DataFrame, months: int = 6, start: str | None = None,
                      end: str | None = None) -> Result:
    """Balance of each month (income - expenses) and the cumulative one in the period."""
    base = income_vs_expenses(df, months, start, end)
    if base.chart is None:
        return base
    labels = base.chart["rotulos"]
    balances = [base.data["por_mes"][r]["saldo"] for r in labels]
    cumulative, running = [], 0.0
    for s in balances:
        running += s
        cumulative.append(_r(running))
    return Result(
        {"periodo": base.data["periodo"], "saldo_por_mes": dict(zip(labels, balances)),
         "saldo_acumulado": cumulative[-1],
         **{k: v for k, v in base.data.items() if k in ("aviso", "sem_extrato_no_periodo")}},
        {"tipo": "linha", "titulo": f"Evolução do saldo ({base.data['periodo']})", "rotulos": labels,
         "series": [{"nome": "Saldo do mês", "valores": balances}, {"nome": "Acumulado", "valores": cumulative}],
         "formato": "moeda"})


def largest_expenses(df: pd.DataFrame, months: int = 1, limit: int = 5, category: str | None = None,
                     start: str | None = None, end: str | None = None) -> Result:
    category = _validate_category(category)
    if df.empty:
        return _empty()
    limit = max(1, min(int(limit), 20))
    window = _window(df, months, start, end)
    d = _expenses(df, with_refunds=False)  # individual purchases: the refund is not a purchase
    d = d[d["mes"].isin(window)]
    if category:
        d = d[d["categoria"] == category]
    top = d.sort_values("gasto", ascending=False).head(limit)
    items = [{"data": t.data.date().isoformat(), "estabelecimento": t.contraparte or "(sem nome)",
              "categoria": CATEGORY_NAMES.get(t.categoria, t.categoria), "valor": _r(t.gasto)}
             for t in top.itertuples()]
    labels = [f"{i['estabelecimento'][:24]} ({i['data'][8:10]}/{i['data'][5:7]})" for i in items]
    return Result(
        {"periodo": _period_label(window), "categoria": category or "todas", "maiores": items,
         **_coverage(df, window)},
        {"tipo": "barras_horizontais", "titulo": f"Maiores gastos ({_period_label(window)})", "rotulos": labels,
         "series": [{"nome": "Valor", "valores": [i["valor"] for i in items]}], "formato": "moeda"} if items else None)


def spending_by_merchant(df: pd.DataFrame, months: int = 3, limit: int = 8,
                         category: str | None = None, start: str | None = None,
                         end: str | None = None) -> Result:
    """Where the money went, adding up the purchases at the same merchant."""
    category = _validate_category(category)
    if df.empty:
        return _empty()
    limit = max(1, min(int(limit), 20))
    window = _window(df, months, start, end)
    d = _expenses(df)
    d = d[d["mes"].isin(window) & (d["contraparte"] != "")]
    if category:
        d = d[d["categoria"] == category]
    d = d.assign(compra=d["gasto"] > 0)  # refunds lower the total, but do not count as a purchase
    groups = d.groupby("contraparte").agg(sum=("gasto", "sum"), count=("compra", "sum"))
    groups = groups[groups["sum"] > 0].sort_values("sum", ascending=False).head(limit)
    items = [{"estabelecimento": name, "total": _r(s), "compras": int(n)} for name, s, n in groups.itertuples()]
    return Result(
        {"periodo": _period_label(window), "categoria": category or "todas", "estabelecimentos": items,
         **_coverage(df, window)},
        {"tipo": "barras_horizontais", "titulo": f"Gastos por estabelecimento ({_period_label(window)})",
         "rotulos": [i["estabelecimento"][:28] for i in items],
         "series": [{"nome": "Total", "valores": [i["total"] for i in items]}], "formato": "moeda"} if items else None)


def _target_month(df: pd.DataFrame, year: int | None, month: int | None) -> pd.Period:
    """The requested month. Without a year, the most recent one with that month (up to the last
    transaction): "September" with data up to Mar/25 is Sep/24. Only the year: the last month with
    transactions in it."""
    last = df["mes"].max()
    if month is None:
        if not year:
            return last
        of_year = df.loc[df["mes"].dt.year == year, "mes"]
        return of_year.max() if not of_year.empty else pd.Period(year=year, month=12, freq="M")
    if not year:
        year = last.year if month <= last.month else last.year - 1
    return pd.Period(year=year, month=month, freq="M")


def month_summary(df: pd.DataFrame, year: int | None = None, month: int | None = None) -> Result:
    """Income, expenses, balance and the categories that weighed the most in a month (default: the most recent)."""
    if df.empty:
        return _empty()
    if month is not None and not 1 <= month <= 12:
        # returns the error to the model instead of raising an exception (which would break the whole answer)
        return Result({"erro": f"mês inválido: {month}. Use um número de 1 a 12."})
    target = _target_month(df, year, month)
    in_month = df[df["mes"] == target]
    # income and refunds over all transactions: the refund of the month may be for a purchase from another month
    income = _income(df)
    inc = float(income.loc[income["mes"] == target, "valor"].sum())
    # the refunds are looked up in all transactions (the purchase may be from another month)
    d = _expenses(df)
    d = d[d["mes"] == target]
    exp = max(0.0, float(d["gasto"].sum()))
    per_category = d.groupby("categoria")["gasto"].sum().sort_values(ascending=False)
    per_category = per_category[per_category > 0]
    items = [{"nome": CATEGORY_NAMES.get(c, c), "total": _r(v)} for c, v in per_category.items()]
    return Result(
        {"mes": _label(target), "tem_transacoes": not in_month.empty, "receitas": _r(inc), "despesas": _r(exp),
         "saldo": _r(inc - exp), "categorias": items[:5]},
        {"tipo": "pizza", "titulo": f"Para onde foi o dinheiro ({_label(target)})",
         "rotulos": [i["nome"] for i in items], "series": [{"nome": "Gasto", "valores": [i["total"] for i in items]}],
         "formato": "moeda"} if items else None)


def available_months(df: pd.DataFrame) -> list[dict[str, str]]:
    """Months with transactions, from the most recent to the oldest: [{"valor": "2024-03", "rotulo": "mar/24"}]."""
    return [{"valor": str(p), "rotulo": _label(p)} for p in sorted(df["mes"].unique(), reverse=True)]


def dashboard(df: pd.DataFrame, month: str | None = None) -> dict[str, Any]:
    """Dashboard cards and chart: one month (default: the most recent) and the 6 months up to it.

    `month` in the "YYYY-MM" format; a month without transactions shows zeros.
    """
    if df.empty:
        return {"tem_dados": False, "mes": None, "mes_valor": None, "meses": [], "receitas": 0.0,
                "despesas": 0.0, "saldo": 0.0, "grafico": None}
    target = pd.Period(month, freq="M") if month else df["mes"].max()
    summary = month_summary(df, target.year, target.month).data
    return {"tem_dados": True, "mes": summary["mes"], "mes_valor": str(target), "meses": available_months(df),
            "receitas": summary["receitas"], "despesas": summary["despesas"], "saldo": summary["saldo"],
            "grafico": income_vs_expenses(df, 6, end=str(target)).chart}
