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
