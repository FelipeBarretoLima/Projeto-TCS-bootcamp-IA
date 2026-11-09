"""Ferramentas do agente (sem chamar o Gemini)."""

from datetime import date

from agente import consultas
from agente.assistente import ferramentas, historico_para_mensagens


def _df():
    return consultas.tabela([{"data": date(2024, 1, 5), "valor": -50, "tipo": "saida", "categoria": "transporte",
                              "contraparte": "POSTO X", "meio": "cartao_debito", "banco": "b"}])


def test_ferramentas_devolvem_so_totais_e_guardam_o_grafico():
    graficos = []
    por_nome = {f.name: f for f in ferramentas(_df(), graficos)}
    assert set(por_nome) == {"gastos_mensais", "gastos_por_categoria", "receitas_x_despesas", "evolucao_saldo",
                             "maiores_gastos", "gastos_por_estabelecimento", "resumo_do_mes", "periodo_disponivel"}
    dados = por_nome["gastos_mensais"].invoke({"meses": 1, "categoria": "transporte"})
    assert dados["total"] == 50.0 and "grafico" not in dados
    assert graficos[-1]["titulo"].startswith("Transporte por mês")


def test_categoria_da_ferramenta_so_aceita_as_8_classes():
    schema = str({f.name: f for f in ferramentas(_df(), [])}["gastos_mensais"].args["categoria"])
    for c in consultas.CATEGORIAS:
        assert c in schema
    assert "lazer" not in schema


def test_historico_vira_mensagens_so_com_o_texto():
    msgs = historico_para_mensagens([
        {"papel": "usuario", "texto": "quanto gastei?"},
        {"papel": "agente", "texto": "R$ 50,00", "grafico": {"titulo": "Gastos por mês"}},
    ])
    assert [(m.type, m.content) for m in msgs] == [("human", "quanto gastei?"), ("ai", "R$ 50,00")]


def test_resposta_sem_nota_de_grafico_inventada():
    from agente.assistente import _limpa

    assert _limpa("Saldo de R$ 10,00.\n\n[gráfico mostrado: Receitas x despesas]") == "Saldo de R$ 10,00."
    assert _limpa("Gastou R$ 5,00 [Gráfico: barras] no mês.") == "Gastou R$ 5,00\nno mês."
