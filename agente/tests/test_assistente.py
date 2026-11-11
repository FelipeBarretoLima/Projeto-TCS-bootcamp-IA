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


def test_ferramenta_aceita_periodo_e_devolve_erro_ao_modelo_em_vez_de_quebrar():
    graficos = []
    por_nome = {f.name: f for f in ferramentas(_df(), graficos)}
    ok = por_nome["gastos_mensais"].invoke({"de": "2024-01", "ate": "2024-12"})
    assert ok["total"] == 50.0 and ok["periodo"] == "jan/24 a dez/24"
    erro = por_nome["gastos_mensais"].invoke({"de": "janeiro"})
    assert "AAAA-MM" in erro["erro"] and len(graficos) == 1  # o erro não gera gráfico


def test_instrucoes_recebem_o_periodo_dos_extratos():
    from agente.assistente import contexto_dos_dados

    assert contexto_dos_dados(_df()) == "\nExtratos enviados: de 05/01/2024 a 05/01/2024 (1 transação)."
    assert "nenhum" in contexto_dos_dados(consultas.tabela([]))
