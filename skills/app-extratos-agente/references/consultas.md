# Consultas fixas (`agent/queries.py`)

Código do projeto de referência. Todas as contas são feitas aqui, com pandas; o LLM só escolhe
qual chamar. Cada função devolve um `Resultado(dados, grafico)`.

## Sumário

1. Preparação e definições
2. Janela de meses e cobertura
3. Consultas
4. Painel do dashboard

## 1. Preparação e definições

```python
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
MAX_MESES = 60  # 5 anos: um extrato longo cabe inteiro


@dataclass
class Resultado:
    dados: dict[str, Any]                          # vai para o LLM: só totais
    grafico: dict[str, Any] | None = field(default=None)  # vai para o frontend


def tabela(transacoes) -> pd.DataFrame:
    """Linhas do banco (ou do CSV do parser) -> DataFrame com os tipos certos."""
    df = pd.DataFrame(list(transacoes), columns=["data", "contraparte", "valor", "tipo", "meio", "banco", "categoria"])
    df["data"] = pd.to_datetime(df["data"])
    df["valor"] = pd.to_numeric(df["valor"]).astype(float)
    df["categoria"] = df["categoria"].fillna("").replace("", "sem_categoria")
    df["contraparte"] = df["contraparte"].fillna("")
    df["mes"] = df["data"].dt.to_period("M")
    return df


def _compras(df):
    """Saídas que são gasto, com a coluna `gasto` (positiva)."""
    d = df[(df["tipo"] == "saida") & (df["categoria"] != "financeiro")].copy()
    d["gasto"] = d["valor"].abs()
    return d


def _estornos_casados(df, compras=None):
    """Estornos que devolvem uma compra: mesmo estabelecimento, compra no mesmo dia ou antes.
    Cada um ganha a categoria da compra mais recente e `gasto` negativo. Mantém o índice de `df`."""
    compras = _compras(df) if compras is None else compras
    estornos = df[(df["tipo"] == "entrada") & (df["meio"] == "estorno") & (df["contraparte"] != "")].copy()
    if estornos.empty or compras.empty:
        return estornos.iloc[0:0].assign(gasto=pd.Series(dtype=float))
    ordenadas = compras.sort_values("data")

    def categoria_da_compra(e):
        antes = ordenadas[(ordenadas["contraparte"] == e["contraparte"]) & (ordenadas["data"] <= e["data"])]
        return antes["categoria"].iloc[-1] if not antes.empty else None

    estornos["categoria"] = estornos.apply(categoria_da_compra, axis=1)
    estornos = estornos[estornos["categoria"].notna()]
    return estornos.assign(gasto=-estornos["valor"].abs())


def _despesas(df, com_estornos=True):
    d = _compras(df)
    if not com_estornos:
        return d
    estornos = _estornos_casados(df, d)
    return pd.concat([d, estornos]) if not estornos.empty else d


def _sem_negativo(serie):
    """Um estorno num mês sem a compra pode deixar o total negativo: mostra zero."""
    return serie.clip(lower=0.0)


def _receitas(df):
    """Entradas `receitas`, menos os estornos que já abateram uma compra (toda entrada é
    categorizada como receita: sem isto, o estorno contaria duas vezes)."""
    r = df[(df["tipo"] == "entrada") & (df["categoria"] == "receitas")]
    return r.drop(index=_estornos_casados(df).index, errors="ignore")
```

## 2. Janela de meses e cobertura

```python
def _mes(texto, campo) -> pd.Period:
    """"2024-03" -> Period. ValueError com mensagem clara (vai para o LLM corrigir)."""
    m = re.fullmatch(r"\s*(\d{4})-(\d{1,2})\s*", str(texto))
    if not m or not 1 <= int(m[2]) <= 12:
        raise ValueError(f"{campo} inválido: {texto!r}. Use o formato AAAA-MM (ex.: 2024-01).")
    return pd.Period(year=int(m[1]), month=int(m[2]), freq="M")


def _janela(df, meses, de=None, ate=None) -> list[pd.Period]:
    """Os N meses que terminam no mês mais recente, ou o intervalo de..ate."""
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


def _cobertura(df, janela) -> dict[str, Any]:
    """Avisa quando parte do período não tem extrato (para o LLM não ler zero como "não gastou")."""
    primeiro, ultimo = df["mes"].min(), df["mes"].max()
    if janela[0] >= primeiro and janela[-1] <= ultimo:
        return {}
    de, ate = df["data"].min().strftime("%d/%m/%Y"), df["data"].max().strftime("%d/%m/%Y")
    if janela[-1] < primeiro or janela[0] > ultimo:
        return {"sem_extrato_no_periodo": True,
                "aviso": f"Não há extrato neste período. Os extratos enviados vão de {de} a {ate}."}
    return {"aviso": f"Parte do período não tem extrato (os extratos enviados vão de {de} a {ate}); "
                     "os meses sem extrato aparecem como zero."}


def _rotulo(p): return f"{_MESES[p.month - 1]}/{str(p.year)[2:]}"
def _periodo(janela): return _rotulo(janela[0]) if len(janela) == 1 else f"{_rotulo(janela[0])} a {_rotulo(janela[-1])}"
def _r(x): return round(float(x), 2)
def _vazio(): return Resultado({"sem_dados": True, "aviso": "O usuário ainda não enviou nenhum extrato."})


def _valida_categoria(categoria):
    if categoria is None or categoria == "":
        return None
    if categoria not in CATEGORIAS:
        raise ValueError(f"categoria inválida: {categoria!r}. Use uma de: {', '.join(CATEGORIAS)}")
    return categoria
```

## 3. Consultas

```python
def periodo_disponivel(df) -> Resultado:
    if df.empty:
        return _vazio()
    return Resultado({"primeira_data": df["data"].min().date().isoformat(),
                      "ultima_data": df["data"].max().date().isoformat(),
                      "transacoes": int(len(df)),
                      "bancos": sorted(df["banco"].dropna().unique().tolist())})


def gastos_mensais(df, meses=6, categoria=None, de=None, ate=None) -> Resultado:
    categoria = _valida_categoria(categoria)
    if df.empty:
        return _vazio()
    janela = _janela(df, meses, de, ate)
    d = _despesas(df)
    if categoria:
        d = d[d["categoria"] == categoria]
    por_mes = _sem_negativo(d.groupby("mes")["gasto"].sum().reindex(janela, fill_value=0.0))
    nome = NOMES_CATEGORIA[categoria] if categoria else "Gastos"
    valores = [_r(v) for v in por_mes]
    return Resultado(
        {"categoria": categoria or "todas", "periodo": _periodo(janela),
         "por_mes": dict(zip(map(_rotulo, janela), valores)), "total": _r(sum(valores)),
         "media_mensal": _r(sum(valores) / len(valores)), **_cobertura(df, janela)},
        {"tipo": "barras", "titulo": f"{nome} por mês ({_periodo(janela)})", "rotulos": [_rotulo(p) for p in janela],
         "series": [{"nome": nome, "valores": valores}], "formato": "moeda"})


def gastos_por_categoria(df, meses=1, de=None, ate=None) -> Resultado:
    if df.empty:
        return _vazio()
    janela = _janela(df, meses, de, ate)
    d = _despesas(df)
    d = d[d["mes"].isin(janela)]
    por_cat = d.groupby("categoria")["gasto"].sum().sort_values(ascending=False)
    por_cat = por_cat[por_cat > 0]
    total = float(por_cat.sum())
    itens = [{"categoria": c, "nome": NOMES_CATEGORIA.get(c, c), "total": _r(v),
              "percentual": _r(100 * v / total) if total else 0.0} for c, v in por_cat.items()]
    return Resultado(
        {"periodo": _periodo(janela), "total_gasto": _r(total), "categorias": itens, **_cobertura(df, janela)},
        {"tipo": "pizza", "titulo": f"Gastos por categoria ({_periodo(janela)})",
         "rotulos": [i["nome"] for i in itens], "series": [{"nome": "Gasto", "valores": [i["total"] for i in itens]}],
         "formato": "moeda"})


def receitas_x_despesas(df, meses=6, de=None, ate=None) -> Resultado:
    if df.empty:
        return _vazio()
    janela = _janela(df, meses, de, ate)
    rec = _receitas(df).groupby("mes")["valor"].sum().reindex(janela, fill_value=0.0)
    desp = _sem_negativo(_despesas(df).groupby("mes")["gasto"].sum().reindex(janela, fill_value=0.0))
    rotulos = [_rotulo(p) for p in janela]
    return Resultado(
        {"periodo": _periodo(janela),
         "por_mes": {r: {"receitas": _r(a), "despesas": _r(b), "saldo": _r(a - b)} for r, a, b in zip(rotulos, rec, desp)},
         "total_receitas": _r(rec.sum()), "total_despesas": _r(desp.sum()), "saldo": _r(rec.sum() - desp.sum()),
         **_cobertura(df, janela)},
        {"tipo": "barras", "titulo": f"Receitas x despesas ({_periodo(janela)})", "rotulos": rotulos,
         "series": [{"nome": "Receitas", "valores": [_r(v) for v in rec]},
                    {"nome": "Despesas", "valores": [_r(v) for v in desp]}], "formato": "moeda"})


def evolucao_saldo(df, meses=6, de=None, ate=None) -> Resultado:
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


def maiores_gastos(df, meses=1, quantidade=5, categoria=None, de=None, ate=None) -> Resultado:
    categoria = _valida_categoria(categoria)
    if df.empty:
        return _vazio()
    quantidade = max(1, min(int(quantidade), 20))
    janela = _janela(df, meses, de, ate)
    d = _despesas(df, com_estornos=False)  # compras individuais: o estorno não é uma compra
    d = d[d["mes"].isin(janela)]
    if categoria:
        d = d[d["categoria"] == categoria]
    top = d.sort_values("gasto", ascending=False).head(quantidade)
    itens = [{"data": t.data.date().isoformat(), "estabelecimento": t.contraparte or "(sem nome)",
              "categoria": NOMES_CATEGORIA.get(t.categoria, t.categoria), "valor": _r(t.gasto)}
             for t in top.itertuples()]
    rotulos = [f"{i['estabelecimento'][:24]} ({i['data'][8:10]}/{i['data'][5:7]})" for i in itens]
    return Resultado(
        {"periodo": _periodo(janela), "categoria": categoria or "todas", "maiores": itens, **_cobertura(df, janela)},
        {"tipo": "barras_horizontais", "titulo": f"Maiores gastos ({_periodo(janela)})", "rotulos": rotulos,
         "series": [{"nome": "Valor", "valores": [i["valor"] for i in itens]}], "formato": "moeda"} if itens else None)


def gastos_por_estabelecimento(df, meses=3, quantidade=8, categoria=None, de=None, ate=None) -> Resultado:
    categoria = _valida_categoria(categoria)
    if df.empty:
        return _vazio()
    quantidade = max(1, min(int(quantidade), 20))
    janela = _janela(df, meses, de, ate)
    d = _despesas(df)
    d = d[d["mes"].isin(janela) & (d["contraparte"] != "")]
    if categoria:
        d = d[d["categoria"] == categoria]
    d = d.assign(compra=d["gasto"] > 0)  # estornos abatem o total, mas não contam como compra
    grupos = d.groupby("contraparte").agg(sum=("gasto", "sum"), count=("compra", "sum"))
    grupos = grupos[grupos["sum"] > 0].sort_values("sum", ascending=False).head(quantidade)
    itens = [{"estabelecimento": nome, "total": _r(s), "compras": int(n)} for nome, s, n in grupos.itertuples()]
    return Resultado(
        {"periodo": _periodo(janela), "categoria": categoria or "todas", "estabelecimentos": itens,
         **_cobertura(df, janela)},
        {"tipo": "barras_horizontais", "titulo": f"Gastos por estabelecimento ({_periodo(janela)})",
         "rotulos": [i["estabelecimento"][:28] for i in itens],
         "series": [{"nome": "Total", "valores": [i["total"] for i in itens]}], "formato": "moeda"} if itens else None)


def _mes_alvo(df, ano, mes) -> pd.Period:
    """Sem ano, o mais recente com aquele mês ("setembro" com dados até mar/25 é set/24).
    Só o ano: o último mês com transações nele."""
    ultimo = df["mes"].max()
    if mes is None:
        if not ano:
            return ultimo
        do_ano = df.loc[df["mes"].dt.year == ano, "mes"]
        return do_ano.max() if not do_ano.empty else pd.Period(year=ano, month=12, freq="M")
    if not ano:
        ano = ultimo.year if mes <= ultimo.month else ultimo.year - 1
    return pd.Period(year=ano, month=mes, freq="M")


def resumo_do_mes(df, ano=None, mes=None) -> Resultado:
    if df.empty:
        return _vazio()
    if mes is not None and not 1 <= mes <= 12:
        return Resultado({"erro": f"mês inválido: {mes}. Use um número de 1 a 12."})
    alvo = _mes_alvo(df, ano, mes)
    no_mes = df[df["mes"] == alvo]
    receitas = _receitas(df)  # sobre todas: o estorno do mês pode ser de compra de outro mês
    rec = float(receitas.loc[receitas["mes"] == alvo, "valor"].sum())
    d = _despesas(df)
    d = d[d["mes"] == alvo]
    desp = max(0.0, float(d["gasto"].sum()))
    por_cat = d.groupby("categoria")["gasto"].sum().sort_values(ascending=False)
    por_cat = por_cat[por_cat > 0]
    itens = [{"nome": NOMES_CATEGORIA.get(c, c), "total": _r(v)} for c, v in por_cat.items()]
    return Resultado(
        {"mes": _rotulo(alvo), "tem_transacoes": not no_mes.empty, "receitas": _r(rec), "despesas": _r(desp),
         "saldo": _r(rec - desp), "categorias": itens[:5]},
        {"tipo": "pizza", "titulo": f"Para onde foi o dinheiro ({_rotulo(alvo)})",
         "rotulos": [i["nome"] for i in itens], "series": [{"nome": "Gasto", "valores": [i["total"] for i in itens]}],
         "formato": "moeda"} if itens else None)
```

## 4. Painel do dashboard

```python
def meses_disponiveis(df) -> list[dict[str, str]]:
    """[{"valor": "2024-03", "rotulo": "mar/24"}, ...], do mais recente ao mais antigo."""
    return [{"valor": str(p), "rotulo": _rotulo(p)} for p in sorted(df["mes"].unique(), reverse=True)]


def painel(df, mes=None) -> dict[str, Any]:
    """Cartões de um mês (padrão: o mais recente) e o gráfico dos 6 meses até ele."""
    if df.empty:
        return {"tem_dados": False, "mes": None, "mes_valor": None, "meses": [], "receitas": 0.0,
                "despesas": 0.0, "saldo": 0.0, "grafico": None}
    alvo = pd.Period(mes, freq="M") if mes else df["mes"].max()
    resumo = resumo_do_mes(df, alvo.year, alvo.month).dados
    return {"tem_dados": True, "mes": resumo["mes"], "mes_valor": str(alvo), "meses": meses_disponiveis(df),
            "receitas": resumo["receitas"], "despesas": resumo["despesas"], "saldo": resumo["saldo"],
            "grafico": receitas_x_despesas(df, 6, ate=str(alvo)).grafico}
```

A rota `GET /api/painel?mes=AAAA-MM` valida o formato (`\d{4}-(0[1-9]|1[0-2])`) antes de chamar
`painel(tabela(db.transacoes(usuario)), mes)`.
