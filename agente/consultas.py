"""Consultas fixas do assistente: transações -> números + gráfico. O LLM só escolhe qual chamar.

Todas as contas são feitas aqui (pandas), nunca pelo LLM. Cada função devolve um `Resultado`:
    dados    o que vai para o LLM escrever a resposta (só totais, nunca a lista de transações,
             exceto `maiores_gastos`, que devolve as N maiores)
    grafico  o que o frontend desenha (None = só texto)

Definições (as mesmas no dashboard e no chat):
    despesa  saída que não é `financeiro` (pagar a fatura, investir ou transferir entre contas
             próprias não é gasto: o gasto já está nas compras do cartão)
    receita  entrada da categoria `receitas`
    "últimos N meses" termina no mês da transação mais recente do usuário, não no mês de hoje:
    quem enviou extratos até outubro vê junho-outubro, não um novembro vazio.
    período explícito: `de` e `ate` ("AAAA-MM", inclusivos) trocam os "últimos N meses" por um
    intervalo fixo (ex.: o ano de 2024 = de="2024-01", ate="2024-12"). Só `de`: até o mês mais
    recente. Só `ate`: os N meses que terminam nele.

Formato do gráfico (o frontend desenha com Recharts):
    {"tipo": "barras" | "barras_horizontais" | "linha" | "pizza", "titulo": str,
     "rotulos": [str], "series": [{"nome": str, "valores": [float]}], "formato": "moeda"}
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
import re
from typing import Any

import pandas as pd

CATEGORIAS = ("mercado", "alimentacao_fora", "transporte", "compras", "contas_servicos",
              "transferencia_pessoa", "receitas", "financeiro")
NOMES_CATEGORIA = {
    "mercado": "Mercado", "alimentacao_fora": "Alimentação fora", "transporte": "Transporte",
    "compras": "Compras", "contas_servicos": "Contas e serviços",
    "transferencia_pessoa": "Transferência p/ pessoa", "receitas": "Receitas",
    "financeiro": "Financeiro", "sem_categoria": "Sem categoria",
}
_MESES = ("jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez")
MAX_MESES = 60  # 5 anos: um extrato longo (ex.: Sicoob 2022-2026) cabe inteiro


@dataclass
class Resultado:
    dados: dict[str, Any]
    grafico: dict[str, Any] | None = field(default=None)


# --- preparação ---

def tabela(transacoes: Iterable[Mapping[str, Any]]) -> pd.DataFrame:
    """Linhas do banco (ou do CSV do parser) -> DataFrame com os tipos certos."""
    df = pd.DataFrame(list(transacoes), columns=["data", "contraparte", "valor", "tipo", "meio", "banco", "categoria"])
    df["data"] = pd.to_datetime(df["data"])
    df["valor"] = pd.to_numeric(df["valor"]).astype(float)
    df["categoria"] = df["categoria"].fillna("").replace("", "sem_categoria")
    df["contraparte"] = df["contraparte"].fillna("")
    df["mes"] = df["data"].dt.to_period("M")
    return df


def _despesas(df: pd.DataFrame) -> pd.DataFrame:
    d = df[(df["tipo"] == "saida") & (df["categoria"] != "financeiro")].copy()
    d["gasto"] = d["valor"].abs()
    return d


def _receitas(df: pd.DataFrame) -> pd.DataFrame:
    return df[(df["tipo"] == "entrada") & (df["categoria"] == "receitas")]


def _mes(texto: str, campo: str) -> pd.Period:
    """"2024-03" -> Period("2024-03"). ValueError com mensagem clara se vier em outro formato."""
    m = re.fullmatch(r"\s*(\d{4})-(\d{1,2})\s*", str(texto))
    if not m or not 1 <= int(m[2]) <= 12:
        raise ValueError(f"{campo} inválido: {texto!r}. Use o formato AAAA-MM (ex.: 2024-01).")
    return pd.Period(year=int(m[1]), month=int(m[2]), freq="M")


def _janela(df: pd.DataFrame, meses: int, de: str | None = None, ate: str | None = None) -> list[pd.Period]:
    """Os meses consultados: os N que terminam no mês mais recente, ou o intervalo `de`..`ate`."""
    fim = _mes(ate, "ate") if ate else df["mes"].max()
    if de:
        inicio = _mes(de, "de")
        if inicio > fim:
            raise ValueError(f"período inválido: 'de' ({de}) é depois de 'ate' ({_rotulo(fim)}).")
        n = (fim - inicio).n + 1
        if n > MAX_MESES:
            raise ValueError(f"período longo demais ({n} meses): o máximo é {MAX_MESES} meses por consulta.")
    else:
        n = max(1, min(int(meses), MAX_MESES))
    return [fim - i for i in range(n - 1, -1, -1)]


def _cobertura(df: pd.DataFrame, janela: list[pd.Period]) -> dict[str, Any]:
    """Avisa quando parte do período pedido não tem extrato (para o LLM não ler zero como "não gastou")."""
    primeiro, ultimo = df["mes"].min(), df["mes"].max()
    if janela[0] >= primeiro and janela[-1] <= ultimo:
        return {}
    de, ate = df["data"].min().strftime("%d/%m/%Y"), df["data"].max().strftime("%d/%m/%Y")
    if janela[-1] < primeiro or janela[0] > ultimo:
        return {"sem_extrato_no_periodo": True,
                "aviso": f"Não há extrato neste período. Os extratos enviados vão de {de} a {ate}."}
    return {"aviso": f"Parte do período não tem extrato (os extratos enviados vão de {de} a {ate}); "
                     "os meses sem extrato aparecem como zero."}


def _rotulo(p: pd.Period) -> str:
    return f"{_MESES[p.month - 1]}/{str(p.year)[2:]}"


def _periodo(janela: list[pd.Period]) -> str:
    return _rotulo(janela[0]) if len(janela) == 1 else f"{_rotulo(janela[0])} a {_rotulo(janela[-1])}"


def _r(x: float) -> float:
    return round(float(x), 2)


def _vazio() -> Resultado:
    return Resultado({"sem_dados": True, "aviso": "O usuário ainda não enviou nenhum extrato."})


def _valida_categoria(categoria: str | None) -> str | None:
    if categoria is None or categoria == "":
        return None
    if categoria not in CATEGORIAS:
        raise ValueError(f"categoria inválida: {categoria!r}. Use uma de: {', '.join(CATEGORIAS)}")
    return categoria


# --- consultas ---

def periodo_disponivel(df: pd.DataFrame) -> Resultado:
    if df.empty:
        return _vazio()
    return Resultado({
        "primeira_data": df["data"].min().date().isoformat(),
        "ultima_data": df["data"].max().date().isoformat(),
        "transacoes": int(len(df)),
        "bancos": sorted(df["banco"].dropna().unique().tolist()),
    })


def gastos_mensais(df: pd.DataFrame, meses: int = 6, categoria: str | None = None,
                   de: str | None = None, ate: str | None = None) -> Resultado:
    """Total gasto em cada mês (numa categoria ou em todas)."""
    categoria = _valida_categoria(categoria)
    if df.empty:
        return _vazio()
    janela = _janela(df, meses, de, ate)
    d = _despesas(df)
    if categoria:
        d = d[d["categoria"] == categoria]
    por_mes = d.groupby("mes")["gasto"].sum().reindex(janela, fill_value=0.0)
    nome = NOMES_CATEGORIA[categoria] if categoria else "Gastos"
    valores = [_r(v) for v in por_mes]
    return Resultado(
        {"categoria": categoria or "todas", "periodo": _periodo(janela),
         "por_mes": dict(zip(map(_rotulo, janela), valores)), "total": _r(sum(valores)),
         "media_mensal": _r(sum(valores) / len(valores)), **_cobertura(df, janela)},
        {"tipo": "barras", "titulo": f"{nome} por mês ({_periodo(janela)})", "rotulos": [_rotulo(p) for p in janela],
         "series": [{"nome": nome, "valores": valores}], "formato": "moeda"})


def gastos_por_categoria(df: pd.DataFrame, meses: int = 1, de: str | None = None,
                         ate: str | None = None) -> Resultado:
    """Quanto foi gasto em cada categoria no período ("onde gastei mais?")."""
    if df.empty:
        return _vazio()
    janela = _janela(df, meses, de, ate)
    d = _despesas(df)
    d = d[d["mes"].isin(janela)]
    por_cat = d.groupby("categoria")["gasto"].sum().sort_values(ascending=False)
    total = float(por_cat.sum())
    itens = [{"categoria": c, "nome": NOMES_CATEGORIA.get(c, c), "total": _r(v),
              "percentual": _r(100 * v / total) if total else 0.0} for c, v in por_cat.items()]
    return Resultado(
        {"periodo": _periodo(janela), "total_gasto": _r(total), "categorias": itens, **_cobertura(df, janela)},
        {"tipo": "barras_horizontais", "titulo": f"Gastos por categoria ({_periodo(janela)})",
         "rotulos": [i["nome"] for i in itens], "series": [{"nome": "Gasto", "valores": [i["total"] for i in itens]}],
         "formato": "moeda"})


def receitas_x_despesas(df: pd.DataFrame, meses: int = 6, de: str | None = None,
                        ate: str | None = None) -> Resultado:
    if df.empty:
        return _vazio()
    janela = _janela(df, meses, de, ate)
    rec = _receitas(df).groupby("mes")["valor"].sum().reindex(janela, fill_value=0.0)
    desp = _despesas(df).groupby("mes")["gasto"].sum().reindex(janela, fill_value=0.0)
    rotulos = [_rotulo(p) for p in janela]
    return Resultado(
        {"periodo": _periodo(janela),
         "por_mes": {r: {"receitas": _r(a), "despesas": _r(b), "saldo": _r(a - b)}
                     for r, a, b in zip(rotulos, rec, desp)},
         "total_receitas": _r(rec.sum()), "total_despesas": _r(desp.sum()), "saldo": _r(rec.sum() - desp.sum()),
         **_cobertura(df, janela)},
        {"tipo": "barras", "titulo": f"Receitas x despesas ({_periodo(janela)})", "rotulos": rotulos,
         "series": [{"nome": "Receitas", "valores": [_r(v) for v in rec]},
                    {"nome": "Despesas", "valores": [_r(v) for v in desp]}], "formato": "moeda"})


def evolucao_saldo(df: pd.DataFrame, meses: int = 6, de: str | None = None,
                   ate: str | None = None) -> Resultado:
    """Saldo de cada mês (receitas - despesas) e o acumulado no período."""
    base = receitas_x_despesas(df, meses, de, ate)
    if base.grafico is None:
        return base
    rotulos = base.grafico["rotulos"]
    saldos = [base.dados["por_mes"][r]["saldo"] for r in rotulos]
    acumulado, soma = [], 0.0
    for s in saldos:
        soma += s
        acumulado.append(_r(soma))
    return Resultado(
        {"periodo": base.dados["periodo"], "saldo_por_mes": dict(zip(rotulos, saldos)),
         "saldo_acumulado": acumulado[-1],
         **{k: v for k, v in base.dados.items() if k in ("aviso", "sem_extrato_no_periodo")}},
        {"tipo": "linha", "titulo": f"Evolução do saldo ({base.dados['periodo']})", "rotulos": rotulos,
         "series": [{"nome": "Saldo do mês", "valores": saldos}, {"nome": "Acumulado", "valores": acumulado}],
         "formato": "moeda"})


def maiores_gastos(df: pd.DataFrame, meses: int = 1, quantidade: int = 5, categoria: str | None = None,
                   de: str | None = None, ate: str | None = None) -> Resultado:
    categoria = _valida_categoria(categoria)
    if df.empty:
        return _vazio()
    quantidade = max(1, min(int(quantidade), 20))
    janela = _janela(df, meses, de, ate)
    d = _despesas(df)
    d = d[d["mes"].isin(janela)]
    if categoria:
        d = d[d["categoria"] == categoria]
    top = d.sort_values("gasto", ascending=False).head(quantidade)
    itens = [{"data": t.data.date().isoformat(), "estabelecimento": t.contraparte or "(sem nome)",
              "categoria": NOMES_CATEGORIA.get(t.categoria, t.categoria), "valor": _r(t.gasto)}
             for t in top.itertuples()]
    rotulos = [f"{i['estabelecimento'][:24]} ({i['data'][8:10]}/{i['data'][5:7]})" for i in itens]
    return Resultado(
        {"periodo": _periodo(janela), "categoria": categoria or "todas", "maiores": itens,
         **_cobertura(df, janela)},
        {"tipo": "barras_horizontais", "titulo": f"Maiores gastos ({_periodo(janela)})", "rotulos": rotulos,
         "series": [{"nome": "Valor", "valores": [i["valor"] for i in itens]}], "formato": "moeda"} if itens else None)


def gastos_por_estabelecimento(df: pd.DataFrame, meses: int = 3, quantidade: int = 8,
                               categoria: str | None = None, de: str | None = None,
                               ate: str | None = None) -> Resultado:
    """Onde o dinheiro foi, somando as compras no mesmo estabelecimento."""
    categoria = _valida_categoria(categoria)
    if df.empty:
        return _vazio()
    quantidade = max(1, min(int(quantidade), 20))
    janela = _janela(df, meses, de, ate)
    d = _despesas(df)
    d = d[d["mes"].isin(janela) & (d["contraparte"] != "")]
    if categoria:
        d = d[d["categoria"] == categoria]
    grupos = d.groupby("contraparte")["gasto"].agg(["sum", "count"]).sort_values("sum", ascending=False).head(quantidade)
    itens = [{"estabelecimento": nome, "total": _r(s), "compras": int(n)} for nome, s, n in grupos.itertuples()]
    return Resultado(
        {"periodo": _periodo(janela), "categoria": categoria or "todas", "estabelecimentos": itens,
         **_cobertura(df, janela)},
        {"tipo": "barras_horizontais", "titulo": f"Gastos por estabelecimento ({_periodo(janela)})",
         "rotulos": [i["estabelecimento"][:28] for i in itens],
         "series": [{"nome": "Total", "valores": [i["total"] for i in itens]}], "formato": "moeda"} if itens else None)


def resumo_do_mes(df: pd.DataFrame, ano: int | None = None, mes: int | None = None) -> Resultado:
    """Receitas, despesas, saldo e as categorias que mais pesaram num mês (padrão: o mais recente)."""
    if df.empty:
        return _vazio()
    alvo = pd.Period(year=ano, month=mes, freq="M") if ano and mes else df["mes"].max()
    no_mes = df[df["mes"] == alvo]
    rec = float(_receitas(no_mes)["valor"].sum())
    d = _despesas(no_mes)
    desp = float(d["gasto"].sum())
    por_cat = d.groupby("categoria")["gasto"].sum().sort_values(ascending=False)
    itens = [{"nome": NOMES_CATEGORIA.get(c, c), "total": _r(v)} for c, v in por_cat.items()]
    return Resultado(
        {"mes": _rotulo(alvo), "tem_transacoes": not no_mes.empty, "receitas": _r(rec), "despesas": _r(desp),
         "saldo": _r(rec - desp), "categorias": itens[:5]},
        {"tipo": "pizza", "titulo": f"Para onde foi o dinheiro ({_rotulo(alvo)})",
         "rotulos": [i["nome"] for i in itens], "series": [{"nome": "Gasto", "valores": [i["total"] for i in itens]}],
         "formato": "moeda"} if itens else None)


def painel(df: pd.DataFrame) -> dict[str, Any]:
    """Cartões e gráfico do dashboard: o mês mais recente e os últimos 6 meses."""
    if df.empty:
        return {"tem_dados": False, "mes": None, "receitas": 0.0, "despesas": 0.0, "saldo": 0.0, "grafico": None}
    resumo = resumo_do_mes(df).dados
    return {"tem_dados": True, "mes": resumo["mes"], "receitas": resumo["receitas"],
            "despesas": resumo["despesas"], "saldo": resumo["saldo"],
            "grafico": receitas_x_despesas(df, 6).grafico}
