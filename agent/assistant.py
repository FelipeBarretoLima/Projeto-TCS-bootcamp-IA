"""TAS assistant: user question -> Gemini picks a fixed query -> text + chart.

Gemini never sees the list of transactions nor does any math: it picks the tool and the parameters
(category, how many months...), the tool computes with pandas (`queries.py`) and returns only the
totals. The chart produced by the tool goes straight to the frontend, without going through the model.

What Gemini reads stays in Portuguese on purpose: the prompt (`INSTRUCTIONS`), the tool names
(`@tool("gastos_mensais")`), their parameters (`meses`, `de`, `ate`...) and their docstrings,
which become the tool descriptions.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

import pandas as pd
from langchain.agents import create_agent
from langchain.agents.middleware import ModelFallbackMiddleware
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.tools import BaseTool, tool

from . import queries

CategoryName = Literal["mercado", "alimentacao_fora", "transporte", "compras", "contas_servicos",
                       "transferencia_pessoa", "receitas", "financeiro"]

INSTRUCTIONS = """\
Você é o Assistente TAS, que responde perguntas sobre as finanças pessoais do usuário a partir
dos extratos bancários que ele enviou. Responda sempre em português do Brasil.

Regras:
- Para QUALQUER número (valores, totais, médias, saldos), chame uma ferramenta. Nunca invente nem
  calcule valores por conta própria: use só os números que as ferramentas devolverem.
- Escolha a ferramenta que responde a pergunta. Cada ferramenta já gera um gráfico que é mostrado
  ao usuário junto com o seu texto; não descreva o gráfico ponto a ponto, comente o que importa.
- Pergunta sobre como os gastos se dividem entre categorias ("onde gastei mais?", "gastos por
  categoria", "com o que eu mais gasto?", "divisão dos gastos", "quanto foi cada categoria"):
  use gastos_por_categoria, que mostra um gráfico de pizza. Só use gastos_mensais quando a
  pergunta for sobre a evolução mês a mês (de todas ou de uma categoria).
- Chame no máximo uma ferramenta por pergunta, a não ser que a pergunta peça duas coisas diferentes.
- Período: por padrão as ferramentas usam os "últimos N meses" (parâmetro `meses`), que terminam
  no mês do extrato mais recente do usuário. Para um período específico, use `de` e `ate` no
  formato AAAA-MM (inclusivos): "em 2024" = de="2024-01", ate="2024-12"; "de março a junho de
  2023" = de="2023-03", ate="2023-06"; "desde janeiro de 2025" = só de="2025-01". Para um único
  mês com receitas, despesas e saldo, use resumo_do_mes. Diga sempre o período usado (ele vem no
  campo "periodo").
- O período dos extratos enviados está no fim destas instruções. Nunca diga que não há dados de
  um período que está dentro dele: consulte com `de`/`ate`. Se a ferramenta devolver "aviso",
  repasse-o ao usuário (meses sem extrato aparecem como zero, o que não quer dizer que ele não
  gastou). Se devolver "erro", corrija os parâmetros e tente de novo.
- Categorias: mercado, alimentacao_fora (restaurantes, delivery, lanches), transporte,
  compras, contas_servicos (contas, assinaturas, saúde), transferencia_pessoa (PIX/TED para
  pessoas), receitas, financeiro (fatura do cartão, investimentos, tarifas). Se o usuário falar de
  "comida" ou "alimentação" sem dizer onde, use alimentacao_fora e mencione que mercado é separado.
- "Despesa" não inclui a categoria financeiro (pagar a fatura não é gasto novo: o gasto já está
  nas compras do cartão).
- Se a ferramenta disser que não há dados, explique que é preciso importar um extrato primeiro.
- Se a pergunta não for sobre as finanças do usuário, NÃO responda o conteúdo dela: diga
  educadamente que você só ajuda com os gastos e extratos dele e sugira uma pergunta.
- Seja breve: 1 a 3 frases, valores no formato R$ 1.234,56.
"""

MAX_HISTORY = 12  # previous messages sent as context


@dataclass
class Answer:
    text: str
    chart: dict[str, Any] | None


def build_tools(df: pd.DataFrame, charts: list[dict[str, Any]]) -> list[BaseTool]:
    """The fixed queries, bound to this user's data. Every chart produced goes to `charts`.

    Invalid parameters (e.g. `de` outside the AAAA-MM format) go back to the model as {"erro": ...}
    so it can fix them: an exception here would break the whole answer (LangChain does not pass it on).
    The tool names, parameters and docstrings are what Gemini reads: they stay in Portuguese.
    """

    def run(query: Callable[[], queries.Result]) -> dict[str, Any]:
        try:
            result = query()
        except ValueError as exc:
            return {"erro": str(exc)}
        if result.chart:
            charts.append(result.chart)
        return result.data

    @tool("gastos_mensais")
    def monthly_spending(meses: int = 6, categoria: CategoryName | None = None, de: str | None = None,
                         ate: str | None = None) -> dict[str, Any]:
        """Total gasto em cada mês, numa categoria ou em todas, com total e média. Ex.: "quanto
        gastei de alimentação nos últimos 6 meses?", "quanto gastei em 2024?" (de="2024-01",
        ate="2024-12"). `de`/`ate` (AAAA-MM) definem um período fixo no lugar de `meses`."""
        return run(lambda: queries.monthly_spending(df, meses, categoria, de, ate))

    @tool("gastos_por_categoria")
    def spending_by_category(meses: int = 1, de: str | None = None, ate: str | None = None) -> dict[str, Any]:
        """Quanto foi gasto em cada categoria no período, do maior para o menor, com o percentual
        de cada uma (gráfico de pizza). Use para qualquer pergunta sobre divisão dos gastos entre
        categorias. Ex.: "onde gastei mais?", "gastos por categoria", "como se dividiram meus gastos
        em 2023?". `de`/`ate` (AAAA-MM) no lugar de `meses`."""
        return run(lambda: queries.spending_by_category(df, meses, de, ate))

    @tool("receitas_x_despesas")
    def income_vs_expenses(meses: int = 6, de: str | None = None, ate: str | None = None) -> dict[str, Any]:
        """Receitas e despesas de cada mês lado a lado, com o saldo. Ex.: "receitas x despesas",
        "ganhei mais do que gastei em 2024?". `de`/`ate` (AAAA-MM) no lugar de `meses`."""
        return run(lambda: queries.income_vs_expenses(df, meses, de, ate))

    @tool("evolucao_saldo")
    def balance_evolution(meses: int = 6, de: str | None = None, ate: str | None = None) -> dict[str, Any]:
        """Saldo de cada mês (receitas menos despesas) e o acumulado. Ex.: "como evoluiu meu saldo?".
        `de`/`ate` (AAAA-MM) no lugar de `meses`."""
        return run(lambda: queries.balance_evolution(df, meses, de, ate))

    @tool("maiores_gastos")
    def largest_expenses(meses: int = 1, quantidade: int = 5, categoria: CategoryName | None = None,
                         de: str | None = None, ate: str | None = None) -> dict[str, Any]:
        """As maiores compras/pagamentos individuais do período. Ex.: "quais foram meus maiores
        gastos este mês?", "a compra mais cara de 2023". `de`/`ate` (AAAA-MM) no lugar de `meses`."""
        return run(lambda: queries.largest_expenses(df, meses, quantidade, categoria, de, ate))

    @tool("gastos_por_estabelecimento")
    def spending_by_merchant(meses: int = 3, quantidade: int = 8, categoria: CategoryName | None = None,
                             de: str | None = None, ate: str | None = None) -> dict[str, Any]:
        """Total gasto em cada estabelecimento (somando as compras repetidas). Ex.: "em que lugar
        eu mais gasto?", "quanto gastei no iFood em 2024?". `de`/`ate` (AAAA-MM) no lugar de `meses`."""
        return run(lambda: queries.spending_by_merchant(df, meses, quantidade, categoria, de, ate))

    @tool("resumo_do_mes")
    def month_summary(ano: int | None = None, mes: int | None = None) -> dict[str, Any]:
        """Receitas, despesas, saldo e principais categorias de um mês (sem ano/mês = o mais
        recente). Ex.: "resumo de setembro", "como foi meu mês?", "como foi março de 2023?"."""
        return run(lambda: queries.month_summary(df, ano, mes))

    @tool("periodo_disponivel")
    def available_period() -> dict[str, Any]:
        """De quando a quando vão os extratos enviados e de quais bancos. Use quando a pergunta
        for sobre os dados disponíveis ou quando outra ferramenta não encontrar o período pedido."""
        return run(lambda: queries.available_period(df))

    return [monthly_spending, spending_by_category, income_vs_expenses, balance_evolution, largest_expenses,
            spending_by_merchant, month_summary, available_period]


def data_context(df: pd.DataFrame) -> str:
    """The statements' period, at the end of the instructions: the model knows beforehand what it can query."""
    if df.empty:
        return "\nExtratos enviados: nenhum ainda."
    return (f"\nExtratos enviados: de {df['data'].min():%d/%m/%Y} a {df['data'].max():%d/%m/%Y} "
            f"({len(df)} {'transação' if len(df) == 1 else 'transações'}).")


def history_to_messages(history: Sequence[dict[str, Any]]) -> list[BaseMessage]:
    """Previous messages of the conversation -> context for the model (text only).

    The chart does not go in: a note like "[gráfico mostrado: ...]" was imitated by the model in the
    following answers. The answer text already says the subject and the period, which is enough for
    questions like "e com transporte?".
    """
    return [HumanMessage(m.get("texto") or "") if m["papel"] == "usuario" else AIMessage(m.get("texto") or "")
            for m in list(history)[-MAX_HISTORY:]]


_CHART_NOTE = re.compile(r"\s*\[gr[aá]fico[^\]]*\]\s*", re.I)


def _clean(text: str) -> str:
    """Removes bracketed notes about the chart, in case the model makes one up."""
    return _CHART_NOTE.sub("\n", text).strip()


@dataclass(frozen=True)
class Models:
    """The primary model and the fallbacks, tried in order if the primary fails (503, timeout...)."""

    primary: Any
    fallbacks: tuple[Any, ...] = ()


def answer(model, df: pd.DataFrame, question: str, history: Sequence[dict[str, Any]] = ()) -> Answer:
    """One assistant round. `model`: a LangChain chat model or `Models` (primary + fallbacks)."""
    charts: list[dict[str, Any]] = []
    primary, fallbacks = (model.primary, model.fallbacks) if isinstance(model, Models) else (model, ())
    agent = create_agent(model=primary, tools=build_tools(df, charts),
                         system_prompt=INSTRUCTIONS + data_context(df),
                         middleware=[ModelFallbackMiddleware(*fallbacks)] if fallbacks else ())
    output = agent.invoke({"messages": [*history_to_messages(history), HumanMessage(question)]},
                          config={"recursion_limit": 8})
    final = output["messages"][-1]
    text = _clean(final.text if hasattr(final, "text") else str(final.content))
    return Answer(text or "Não consegui responder agora. Tente reformular a pergunta.",
                  pick_chart(charts))


def pick_chart(charts: list[dict[str, Any]]) -> dict[str, Any] | None:
    """One chart per answer: the pie (split by category), if the agent produced one; otherwise, the last one."""
    pies = [g for g in charts if g.get("tipo") == "pizza"]
    return pies[-1] if pies else (charts[-1] if charts else None)


def gemini_model(key: str, name: str, timeout: float = 15):
    from langchain_google_genai import ChatGoogleGenerativeAI

    # "minimal" thinking: Gemini's "reasoning" made some answers take ~30 s; here it only picks a
    # tool and summarizes ready-made numbers, which needs no long reasoning (measured: from 2-33 s
    # to ~1.6 s per question, with the same answers). The 2.x models use thinking_budget instead of
    # thinking_level.
    thinking = {"thinking_budget": 0} if name.startswith("gemini-2") else {"thinking_level": "minimal"}
    # max_retries=0: an overloaded model (503) does not get better by repeating; the one that tries
    # again is the next model in the list (ModelFallbackMiddleware), without the user waiting minutes
    return ChatGoogleGenerativeAI(model=name, api_key=key, temperature=0, max_retries=0, timeout=timeout,
                                  **thinking)


def gemini_models(key: str, primary: str, fallbacks: Sequence[str] = (), timeout: float = 15) -> Models:
    """The primary and the fallbacks (without repeating the primary), all with the same timeout."""
    names = [n for n in dict.fromkeys(fallbacks) if n != primary]
    return Models(gemini_model(key, primary, timeout), tuple(gemini_model(key, n, timeout) for n in names))
