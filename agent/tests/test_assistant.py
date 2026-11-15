"""Agent tools (without calling Gemini)."""

from datetime import date

from agent import queries
from agent.assistant import build_tools, history_to_messages


def _df():
    return queries.to_dataframe([{"data": date(2024, 1, 5), "valor": -50, "tipo": "saida", "categoria": "transporte",
                                  "contraparte": "POSTO X", "meio": "cartao_debito", "banco": "b"}])


def test_tools_return_only_totals_and_keep_the_chart():
    charts = []
    by_name = {f.name: f for f in build_tools(_df(), charts)}
    assert set(by_name) == {"gastos_mensais", "gastos_por_categoria", "receitas_x_despesas", "evolucao_saldo",
                            "maiores_gastos", "gastos_por_estabelecimento", "resumo_do_mes", "periodo_disponivel"}
    data = by_name["gastos_mensais"].invoke({"meses": 1, "categoria": "transporte"})
    assert data["total"] == 50.0 and "grafico" not in data
    assert charts[-1]["titulo"].startswith("Transporte por mês")


def test_tool_category_only_accepts_the_8_classes():
    schema = str({f.name: f for f in build_tools(_df(), [])}["gastos_mensais"].args["categoria"])
    for c in queries.CATEGORIES:
        assert c in schema
    assert "lazer" not in schema


def test_history_becomes_messages_with_text_only():
    msgs = history_to_messages([
        {"papel": "usuario", "texto": "quanto gastei?"},
        {"papel": "agente", "texto": "R$ 50,00", "grafico": {"titulo": "Gastos por mês"}},
    ])
    assert [(m.type, m.content) for m in msgs] == [("human", "quanto gastei?"), ("ai", "R$ 50,00")]


def test_answer_without_made_up_chart_note():
    from agent.assistant import _clean

    assert _clean("Saldo de R$ 10,00.\n\n[gráfico mostrado: Receitas x despesas]") == "Saldo de R$ 10,00."
    assert _clean("Gastou R$ 5,00 [Gráfico: barras] no mês.") == "Gastou R$ 5,00\nno mês."


def test_tool_accepts_period_and_returns_error_to_the_model_instead_of_breaking():
    charts = []
    by_name = {f.name: f for f in build_tools(_df(), charts)}
    ok = by_name["gastos_mensais"].invoke({"de": "2024-01", "ate": "2024-12"})
    assert ok["total"] == 50.0 and ok["periodo"] == "jan/24 a dez/24"
    error = by_name["gastos_mensais"].invoke({"de": "janeiro"})
    assert "AAAA-MM" in error["erro"] and len(charts) == 1  # the error produces no chart


def test_instructions_receive_the_statements_period():
    from agent.assistant import data_context

    assert data_context(_df()) == "\nExtratos enviados: de 05/01/2024 a 05/01/2024 (1 transação)."
    assert "nenhum" in data_context(queries.to_dataframe([]))


def test_pie_has_priority_when_the_agent_produces_more_than_one_chart():
    from agent.assistant import pick_chart

    bars = {"tipo": "barras", "titulo": "Gastos por mês"}
    pie = {"tipo": "pizza", "titulo": "Gastos por categoria"}
    assert pick_chart([pie, bars]) is pie
    assert pick_chart([bars]) is bars
    assert pick_chart([]) is None


def test_category_tool_produces_pie():
    charts = []
    by_name = {f.name: f for f in build_tools(_df(), charts)}
    by_name["gastos_por_categoria"].invoke({"meses": 1})
    assert charts[-1]["tipo"] == "pizza"
    assert "pizza" in by_name["gastos_por_categoria"].description


# --- fallback model (without calling Gemini) ---

from langchain_core.language_models.chat_models import BaseChatModel  # noqa: E402
from langchain_core.messages import AIMessage  # noqa: E402
from langchain_core.outputs import ChatGeneration, ChatResult  # noqa: E402


class _FakeModel(BaseChatModel):
    """Answers a fixed text, or fails like an overloaded Gemini."""

    text: str = ""
    fails: bool = False
    calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "falso"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        if self.fails:
            raise RuntimeError("503 UNAVAILABLE: This model is currently experiencing high demand")
        return ChatResult(generations=[ChatGeneration(message=AIMessage(self.text))])


def test_overloaded_primary_falls_back():
    from agent.assistant import Models, answer

    primary, fallback = _FakeModel(fails=True), _FakeModel(text="Resposta do reserva.")
    r = answer(Models(primary, (fallback,)), _df(), "oi")
    assert r.text == "Resposta do reserva."
    assert primary.calls == 1 and fallback.calls == 1  # without repeating the primary


def test_without_fallback_the_primary_error_is_raised():
    import pytest

    from agent.assistant import Models, answer

    with pytest.raises(RuntimeError, match="503"):
        answer(Models(_FakeModel(fails=True)), _df(), "oi")


def test_model_list_does_not_repeat_the_primary():
    from agent.assistant import gemini_models

    m = gemini_models("chave-falsa", "gemini-3.5-flash-lite",
                      ["gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-3.6-flash"], timeout=7)
    assert m.primary.model.endswith("gemini-3.5-flash-lite")
    assert [r.model.split("/")[-1] for r in m.fallbacks] == ["gemini-3.6-flash"]
    assert m.primary.max_retries == 0 and m.primary.timeout == 7
