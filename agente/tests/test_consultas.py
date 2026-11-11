"""Consultas do assistente com transações inventadas."""

from datetime import date

import pytest

from agente import consultas as c


def _t(data, valor, tipo="saida", categoria="mercado", contraparte="LOJA FICTICIA", meio="cartao_debito"):
    return {"data": data, "valor": valor, "tipo": tipo, "categoria": categoria, "contraparte": contraparte,
            "meio": meio, "banco": "banco_teste"}


@pytest.fixture
def df():
    return c.tabela([
        _t(date(2024, 1, 10), 5000, "entrada", "receitas", "", "salario"),
        _t(date(2024, 1, 11), -300, categoria="mercado"),
        _t(date(2024, 1, 12), -80, categoria="alimentacao_fora", contraparte="PIZZARIA X"),
        _t(date(2024, 1, 20), -1500, categoria="financeiro", meio="pagamento_fatura"),  # não é despesa
        _t(date(2024, 3, 5), 5000, "entrada", "receitas", "", "salario"),
        _t(date(2024, 3, 6), -120, categoria="alimentacao_fora", contraparte="PIZZARIA X"),
        _t(date(2024, 3, 7), -40, categoria="alimentacao_fora", contraparte="LANCHE Y"),
        _t(date(2024, 3, 8), -900, categoria="compras", contraparte="LOJA Z"),
        _t(date(2024, 3, 9), -50, categoria=None, contraparte="DESCONHECIDA"),
        _t(date(2024, 3, 10), 30, "entrada", "financeiro", "", "estorno"),  # não é receita
    ])


def test_janela_termina_no_mes_mais_recente_e_inclui_meses_vazios(df):
    r = c.gastos_mensais(df, 3, "alimentacao_fora")
    assert r.dados["por_mes"] == {"jan/24": 80.0, "fev/24": 0.0, "mar/24": 160.0}
    assert r.dados["total"] == 240.0 and r.dados["periodo"] == "jan/24 a mar/24"
    assert r.grafico["rotulos"] == ["jan/24", "fev/24", "mar/24"]


def test_financeiro_nao_conta_como_despesa_e_sem_categoria_conta(df):
    r = c.gastos_mensais(df, 3)
    assert r.dados["por_mes"]["jan/24"] == 380.0      # sem os 1500 da fatura
    assert r.dados["por_mes"]["mar/24"] == 1110.0     # inclui os 50 sem categoria


def test_gastos_por_categoria_ordenado_com_percentual(df):
    r = c.gastos_por_categoria(df, 1)
    cats = r.dados["categorias"]
    assert [x["categoria"] for x in cats] == ["compras", "alimentacao_fora", "sem_categoria"]
    assert r.dados["total_gasto"] == 1110.0 and cats[0]["percentual"] == 81.08


def test_receitas_x_despesas_e_saldo(df):
    r = c.receitas_x_despesas(df, 3)
    assert r.dados["por_mes"]["mar/24"] == {"receitas": 5000.0, "despesas": 1110.0, "saldo": 3890.0}
    assert [s["nome"] for s in r.grafico["series"]] == ["Receitas", "Despesas"]
    e = c.evolucao_saldo(df, 3)
    assert e.dados["saldo_por_mes"] == {"jan/24": 4620.0, "fev/24": 0.0, "mar/24": 3890.0}
    assert e.dados["saldo_acumulado"] == 8510.0


def test_maiores_gastos_e_por_estabelecimento(df):
    m = c.maiores_gastos(df, 3, 2)
    assert [(x["estabelecimento"], x["valor"]) for x in m.dados["maiores"]] == [
        ("LOJA Z", 900.0), ("LOJA FICTICIA", 300.0)]
    e = c.gastos_por_estabelecimento(df, 3, categoria="alimentacao_fora")
    assert e.dados["estabelecimentos"][0] == {"estabelecimento": "PIZZARIA X", "total": 200.0, "compras": 2}


def test_resumo_do_mes(df):
    r = c.resumo_do_mes(df, 2024, 1)
    assert (r.dados["receitas"], r.dados["despesas"], r.dados["saldo"]) == (5000.0, 380.0, 4620.0)
    assert r.grafico["tipo"] == "pizza"
    assert c.resumo_do_mes(df).dados["mes"] == "mar/24"


def test_sem_dados_e_categoria_invalida(df):
    vazio = c.tabela([])
    assert c.gastos_mensais(vazio).dados["sem_dados"] is True
    assert c.painel(vazio)["tem_dados"] is False
    with pytest.raises(ValueError, match="categoria inválida"):
        c.gastos_mensais(df, 3, "lazer")


def test_meses_fora_do_limite_sao_ajustados(df):
    assert len(c.gastos_mensais(df, 0).grafico["rotulos"]) == 1
    assert len(c.gastos_mensais(df, 500).grafico["rotulos"]) == c.MAX_MESES


# --- período explícito (de/ate) ---

@pytest.fixture
def anos():
    """Transações de 2022 a 2024, como um extrato longo (o mês mais recente é dez/24)."""
    return c.tabela([
        _t(date(2022, 3, 10), -100, categoria="mercado"),
        _t(date(2023, 6, 10), -200, categoria="mercado"),
        _t(date(2024, 1, 10), -300, categoria="transporte", contraparte="POSTO X"),
        _t(date(2024, 12, 10), -400, categoria="mercado"),
        _t(date(2024, 12, 15), 2000, "entrada", "receitas", "", "salario"),
    ])


def test_ano_especifico_fora_dos_ultimos_meses(anos):
    r = c.gastos_mensais(anos, de="2023-01", ate="2023-12")
    assert r.dados["periodo"] == "jan/23 a dez/23" and r.dados["total"] == 200.0
    assert len(r.grafico["rotulos"]) == 12 and "aviso" not in r.dados


def test_so_de_vai_ate_o_mes_mais_recente(anos):
    r = c.gastos_mensais(anos, de="2024-01")
    assert r.dados["periodo"] == "jan/24 a dez/24" and r.dados["total"] == 700.0


def test_so_ate_usa_os_n_meses_que_terminam_nele(anos):
    r = c.gastos_mensais(anos, 3, ate="2022-04")
    assert r.dados["periodo"] == "fev/22 a abr/22" and r.dados["total"] == 100.0


def test_todas_as_consultas_aceitam_o_periodo(anos):
    assert c.gastos_por_categoria(anos, de="2022-01", ate="2022-12").dados["total_gasto"] == 100.0
    assert c.receitas_x_despesas(anos, de="2024-12", ate="2024-12").dados["saldo"] == 1600.0
    assert c.evolucao_saldo(anos, de="2024-01", ate="2024-12").dados["saldo_acumulado"] == 1300.0
    assert c.maiores_gastos(anos, de="2023-01", ate="2023-12").dados["maiores"][0]["valor"] == 200.0
    assert c.gastos_por_estabelecimento(anos, de="2024-01", ate="2024-01").dados["estabelecimentos"] == [
        {"estabelecimento": "POSTO X", "total": 300.0, "compras": 1}]


def test_periodo_sem_extrato_avisa_em_vez_de_so_dar_zero(anos):
    r = c.gastos_mensais(anos, de="2021-01", ate="2021-12")
    assert r.dados["total"] == 0.0 and r.dados["sem_extrato_no_periodo"] is True
    assert "10/03/2022 a 15/12/2024" in r.dados["aviso"]
    parcial = c.gastos_mensais(anos, de="2021-12", ate="2022-03")
    assert "sem_extrato_no_periodo" not in parcial.dados and "Parte do período" in parcial.dados["aviso"]
    assert "aviso" in c.evolucao_saldo(anos, de="2025-01", ate="2025-02").dados


@pytest.mark.parametrize("de, ate, erro", [
    ("2024", None, "de inválido"),
    ("2024-13", None, "de inválido"),
    ("01/2024", None, "de inválido"),
    ("2024-05", "2024-02", "período inválido"),
    ("2019-01", "2024-12", "período longo demais"),
])
def test_periodo_invalido(anos, de, ate, erro):
    with pytest.raises(ValueError, match=erro):
        c.gastos_mensais(anos, de=de, ate=ate)


# --- mês do resumo e estornos ---

def test_resumo_so_com_o_mes_usa_o_ano_mais_recente_com_aquele_mes(df):
    # dados até mar/24: "janeiro" é jan/24 e "dezembro" é dez/23 (não o mês mais recente)
    assert c.resumo_do_mes(df, None, 1).dados["mes"] == "jan/24"
    assert c.resumo_do_mes(df, None, 1).dados["despesas"] == 380.0
    assert c.resumo_do_mes(df, None, 12).dados["mes"] == "dez/23"
    assert c.resumo_do_mes(df, 2024, None).dados["mes"] == "mar/24"


def test_resumo_com_mes_invalido_devolve_erro_sem_excecao(df):
    assert "erro" in c.resumo_do_mes(df, 2024, 13).dados


def test_estorno_abate_a_compra_no_mesmo_estabelecimento():
    # toda entrada é categorizada como receita (api/servicos/categorizacao.py), o estorno também
    df = c.tabela([
        _t(date(2024, 3, 1), -100, categoria="compras", contraparte="LOJA Z"),
        _t(date(2024, 3, 2), -30, categoria="transporte", contraparte="UBER"),
        _t(date(2024, 3, 5), 100, "entrada", "receitas", "LOJA Z", "estorno"),
        _t(date(2024, 3, 6), 15, "entrada", "receitas", "SEM COMPRA", "estorno"),  # sem compra: é receita
    ])
    assert c.gastos_mensais(df, 1).dados["total"] == 30.0
    # o estorno da LOJA Z já abateu a compra: não conta de novo como receita (só os 15 sem compra)
    assert c.receitas_x_despesas(df, 1).dados["por_mes"]["mar/24"] == {
        "receitas": 15.0, "despesas": 30.0, "saldo": -15.0}
    assert (c.resumo_do_mes(df).dados["receitas"], c.painel(df)["receitas"]) == (15.0, 15.0)
    assert [x["categoria"] for x in c.gastos_por_categoria(df, 1).dados["categorias"]] == ["transporte"]
    assert c.resumo_do_mes(df).dados["despesas"] == 30.0
    assert c.gastos_por_estabelecimento(df, 1).dados["estabelecimentos"] == [
        {"estabelecimento": "UBER", "total": 30.0, "compras": 1}]
    # a compra continua sendo uma das maiores compras do período
    assert c.maiores_gastos(df, 1).dados["maiores"][0]["valor"] == 100.0


def test_estorno_em_mes_sem_a_compra_nao_deixa_o_mes_negativo():
    df = c.tabela([
        _t(date(2024, 2, 1), -100, categoria="compras", contraparte="LOJA Z"),
        _t(date(2024, 3, 5), 100, "entrada", "receitas", "LOJA Z", "estorno"),
    ])
    assert c.gastos_mensais(df, 2).dados["por_mes"] == {"fev/24": 100.0, "mar/24": 0.0}
    assert c.receitas_x_despesas(df, 1).dados["total_despesas"] == 0.0
    # o resumo de março também vê a compra de fevereiro: o estorno não vira receita no mês
    assert c.resumo_do_mes(df, 2024, 3).dados["receitas"] == 0.0
