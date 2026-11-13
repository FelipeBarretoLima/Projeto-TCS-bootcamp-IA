# Prompt, ferramentas e o agente (`agent/assistant.py`)

Código do projeto de referência. O prompt foi ajustado com perguntas reais. Cada regra resolve um
erro observado: ao mudar, teste de novo as perguntas de exemplo.

## Sumário

1. Prompt de sistema
2. Ferramentas
3. Contexto, histórico e limpeza
4. Modelos e `responde`
5. Teste da reserva com um modelo falso

## 1. Prompt de sistema

```python
INSTRUCOES = """\
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

HISTORICO_MAXIMO = 12  # mensagens anteriores enviadas como contexto
```

Troque "Assistente TAS" pelo nome do produto.

## 2. Ferramentas

```python
from typing import Any, Literal

from langchain_core.tools import BaseTool, tool

from . import queries

Categoria = Literal["mercado", "alimentacao_fora", "transporte", "compras", "contas_servicos",
                    "transferencia_pessoa", "receitas", "financeiro"]


def ferramentas(df, graficos: list[dict[str, Any]]) -> list[BaseTool]:
    """As consultas fixas, presas aos dados deste usuário. Cada gráfico gerado vai para `graficos`.

    Parâmetros inválidos voltam ao modelo como {"erro": ...} para ele corrigir: uma exceção aqui
    derrubaria a resposta inteira.
    """

    def roda(consulta) -> dict[str, Any]:
        try:
            resultado = consulta()
        except ValueError as exc:
            return {"erro": str(exc)}
        if resultado.grafico:
            graficos.append(resultado.grafico)
        return resultado.dados

    @tool
    def gastos_mensais(meses: int = 6, categoria: Categoria | None = None, de: str | None = None,
                       ate: str | None = None) -> dict[str, Any]:
        """Total gasto em cada mês, numa categoria ou em todas, com total e média. Ex.: "quanto
        gastei de alimentação nos últimos 6 meses?", "quanto gastei em 2024?" (de="2024-01",
        ate="2024-12"). `de`/`ate` (AAAA-MM) definem um período fixo no lugar de `meses`."""
        return roda(lambda: queries.gastos_mensais(df, meses, categoria, de, ate))

    @tool
    def gastos_por_categoria(meses: int = 1, de: str | None = None, ate: str | None = None) -> dict[str, Any]:
        """Quanto foi gasto em cada categoria no período, do maior para o menor, com o percentual
        de cada uma (gráfico de pizza). Use para qualquer pergunta sobre divisão dos gastos entre
        categorias. Ex.: "onde gastei mais?", "gastos por categoria", "como se dividiram meus gastos
        em 2023?". `de`/`ate` (AAAA-MM) no lugar de `meses`."""
        return roda(lambda: queries.gastos_por_categoria(df, meses, de, ate))

    @tool
    def receitas_x_despesas(meses: int = 6, de: str | None = None, ate: str | None = None) -> dict[str, Any]:
        """Receitas e despesas de cada mês lado a lado, com o saldo. Ex.: "receitas x despesas",
        "ganhei mais do que gastei em 2024?". `de`/`ate` (AAAA-MM) no lugar de `meses`."""
        return roda(lambda: queries.receitas_x_despesas(df, meses, de, ate))

    @tool
    def evolucao_saldo(meses: int = 6, de: str | None = None, ate: str | None = None) -> dict[str, Any]:
        """Saldo de cada mês (receitas menos despesas) e o acumulado. Ex.: "como evoluiu meu saldo?".
        `de`/`ate` (AAAA-MM) no lugar de `meses`."""
        return roda(lambda: queries.evolucao_saldo(df, meses, de, ate))

    @tool
    def maiores_gastos(meses: int = 1, quantidade: int = 5, categoria: Categoria | None = None,
                       de: str | None = None, ate: str | None = None) -> dict[str, Any]:
        """As maiores compras/pagamentos individuais do período. Ex.: "quais foram meus maiores
        gastos este mês?", "a compra mais cara de 2023". `de`/`ate` (AAAA-MM) no lugar de `meses`."""
        return roda(lambda: queries.maiores_gastos(df, meses, quantidade, categoria, de, ate))

    @tool
    def gastos_por_estabelecimento(meses: int = 3, quantidade: int = 8, categoria: Categoria | None = None,
                                   de: str | None = None, ate: str | None = None) -> dict[str, Any]:
        """Total gasto em cada estabelecimento (somando as compras repetidas). Ex.: "em que lugar
        eu mais gasto?", "quanto gastei no iFood em 2024?". `de`/`ate` (AAAA-MM) no lugar de `meses`."""
        return roda(lambda: queries.gastos_por_estabelecimento(df, meses, quantidade, categoria, de, ate))

    @tool
    def resumo_do_mes(ano: int | None = None, mes: int | None = None) -> dict[str, Any]:
        """Receitas, despesas, saldo e principais categorias de um mês (sem ano/mês = o mais
        recente). Ex.: "resumo de setembro", "como foi meu mês?", "como foi março de 2023?"."""
        return roda(lambda: queries.resumo_do_mes(df, ano, mes))

    @tool
    def periodo_disponivel() -> dict[str, Any]:
        """De quando a quando vão os extratos enviados e de quais bancos. Use quando a pergunta
        for sobre os dados disponíveis ou quando outra ferramenta não encontrar o período pedido."""
        return roda(lambda: queries.periodo_disponivel(df))

    return [gastos_mensais, gastos_por_categoria, receitas_x_despesas, evolucao_saldo, maiores_gastos,
            gastos_por_estabelecimento, resumo_do_mes, periodo_disponivel]
```

## 3. Contexto, histórico e limpeza

```python
import re

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage


def contexto_dos_dados(df) -> str:
    """O período dos extratos, no fim das instruções: o modelo sabe de antemão o que pode consultar."""
    if df.empty:
        return "\nExtratos enviados: nenhum ainda."
    return (f"\nExtratos enviados: de {df['data'].min():%d/%m/%Y} a {df['data'].max():%d/%m/%Y} "
            f"({len(df)} {'transação' if len(df) == 1 else 'transações'}).")


def historico_para_mensagens(historico) -> list[BaseMessage]:
    """Mensagens anteriores -> contexto (só o texto; o gráfico não entra, ver SKILL.md)."""
    return [HumanMessage(m.get("texto") or "") if m["papel"] == "usuario" else AIMessage(m.get("texto") or "")
            for m in list(historico)[-HISTORICO_MAXIMO:]]


_NOTA_DE_GRAFICO = re.compile(r"\s*\[gr[aá]fico[^\]]*\]\s*", re.I)


def _limpa(texto: str) -> str:
    """Tira notas entre colchetes sobre o gráfico, caso o modelo invente uma."""
    return _NOTA_DE_GRAFICO.sub("\n", texto).strip()
```

## 4. Modelos e `responde`

```python
from dataclasses import dataclass

from langchain.agents import create_agent
from langchain.agents.middleware import ModelFallbackMiddleware


@dataclass
class Resposta:
    texto: str
    grafico: dict[str, Any] | None


@dataclass(frozen=True)
class Modelos:
    """O modelo principal e os reservas, tentados em ordem se o principal falhar (503, demora...)."""
    principal: Any
    reservas: tuple[Any, ...] = ()


def responde(modelo, df, pergunta: str, historico=()) -> Resposta:
    """Uma rodada do assistente. `modelo`: um chat model do LangChain ou `Modelos`."""
    graficos: list[dict[str, Any]] = []
    principal, reservas = (modelo.principal, modelo.reservas) if isinstance(modelo, Modelos) else (modelo, ())
    agente = create_agent(model=principal, tools=ferramentas(df, graficos),
                          system_prompt=INSTRUCOES + contexto_dos_dados(df),
                          middleware=[ModelFallbackMiddleware(*reservas)] if reservas else ())
    saida = agente.invoke({"messages": [*historico_para_mensagens(historico), HumanMessage(pergunta)]},
                          config={"recursion_limit": 8})
    final = saida["messages"][-1]
    texto = _limpa(final.text if hasattr(final, "text") else str(final.content))
    return Resposta(texto or "Não consegui responder agora. Tente reformular a pergunta.",
                    escolhe_grafico(graficos))


def escolhe_grafico(graficos) -> dict[str, Any] | None:
    """Um gráfico por resposta: a pizza, se o agente gerou uma; senão, o último."""
    pizzas = [g for g in graficos if g.get("tipo") == "pizza"]
    return pizzas[-1] if pizzas else (graficos[-1] if graficos else None)


def modelo_gemini(chave: str, nome: str, timeout: float = 15):
    from langchain_google_genai import ChatGoogleGenerativeAI

    # raciocínio mínimo: a tarefa é escolher uma ferramenta e resumir números prontos
    # (medido: de 2-33 s para ~1,6 s por pergunta, com as mesmas respostas)
    raciocinio = {"thinking_budget": 0} if nome.startswith("gemini-2") else {"thinking_level": "minimal"}
    # max_retries=0: modelo sobrecarregado não melhora repetindo; quem tenta de novo é o reserva
    return ChatGoogleGenerativeAI(model=nome, api_key=chave, temperature=0, max_retries=0, timeout=timeout,
                                  **raciocinio)


def modelos_gemini(chave: str, principal: str, reservas=(), timeout: float = 15) -> Modelos:
    """O principal e os reservas (sem repetir o principal), todos com o mesmo tempo máximo."""
    nomes = [n for n in dict.fromkeys(reservas) if n != principal]
    return Modelos(modelo_gemini(chave, principal, timeout), tuple(modelo_gemini(chave, n, timeout) for n in nomes))
```

## 5. Teste da reserva com um modelo falso

```python
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class _ModeloFalso(BaseChatModel):
    """Responde um texto fixo, ou falha como o LLM sobrecarregado."""

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
    principal, reserva = _ModeloFalso(falha=True), _ModeloFalso(texto="Resposta do reserva.")
    r = responde(Modelos(principal, (reserva,)), _df(), "oi")
    assert r.texto == "Resposta do reserva."
    assert principal.chamadas == 1 and reserva.chamadas == 1  # sem repetir o principal


def test_ferramenta_devolve_erro_ao_modelo_em_vez_de_quebrar():
    graficos = []
    por_nome = {f.name: f for f in ferramentas(_df(), graficos)}
    erro = por_nome["gastos_mensais"].invoke({"de": "janeiro"})
    assert "AAAA-MM" in erro["erro"] and graficos == []
```

`_df()` monta um DataFrame com `queries.tabela([...])` e uma ou duas transações inventadas.
