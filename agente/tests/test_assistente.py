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


def test_pizza_tem_prioridade_quando_o_agente_gera_mais_de_um_grafico():
    from agente.assistente import escolhe_grafico

    barras = {"tipo": "barras", "titulo": "Gastos por mês"}
    pizza = {"tipo": "pizza", "titulo": "Gastos por categoria"}
    assert escolhe_grafico([pizza, barras]) is pizza
    assert escolhe_grafico([barras]) is barras
    assert escolhe_grafico([]) is None


def test_ferramenta_de_categorias_gera_pizza():
    graficos = []
    por_nome = {f.name: f for f in ferramentas(_df(), graficos)}
    por_nome["gastos_por_categoria"].invoke({"meses": 1})
    assert graficos[-1]["tipo"] == "pizza"
    assert "pizza" in por_nome["gastos_por_categoria"].description


# --- modelo reserva (sem chamar o Gemini) ---

from langchain_core.language_models.chat_models import BaseChatModel  # noqa: E402
from langchain_core.messages import AIMessage  # noqa: E402
from langchain_core.outputs import ChatGeneration, ChatResult  # noqa: E402


class _ModeloFalso(BaseChatModel):
    """Responde um texto fixo, ou falha como o Gemini sobrecarregado."""

    texto: str = ""
    falha: bool = False
    chamadas: int = 0

    @property
    def _llm_type(self) -> str:
        return "falso"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.chamadas += 1
        if self.falha:
            raise RuntimeError("503 UNAVAILABLE: This model is currently experiencing high demand")
        return ChatResult(generations=[ChatGeneration(message=AIMessage(self.texto))])


def test_principal_sobrecarregado_passa_para_o_reserva():
    from agente.assistente import Modelos, responde

    principal, reserva = _ModeloFalso(falha=True), _ModeloFalso(texto="Resposta do reserva.")
    r = responde(Modelos(principal, (reserva,)), _df(), "oi")
    assert r.texto == "Resposta do reserva."
    assert principal.chamadas == 1 and reserva.chamadas == 1  # sem repetir o principal


def test_sem_reserva_o_erro_do_principal_sobe():
    import pytest

    from agente.assistente import Modelos, responde

    with pytest.raises(RuntimeError, match="503"):
        responde(Modelos(_ModeloFalso(falha=True)), _df(), "oi")


def test_lista_de_modelos_nao_repete_o_principal():
    from agente.assistente import modelos_gemini

    m = modelos_gemini("chave-falsa", "gemini-3.5-flash-lite",
                       ["gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-3.6-flash"], timeout=7)
    assert m.principal.model.endswith("gemini-3.5-flash-lite")
    assert [r.model.split("/")[-1] for r in m.reservas] == ["gemini-3.6-flash"]
    assert m.principal.max_retries == 0 and m.principal.timeout == 7
