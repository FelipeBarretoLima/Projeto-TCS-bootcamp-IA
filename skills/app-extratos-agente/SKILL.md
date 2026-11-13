---
name: app-extratos-agente
description: Como construir o assistente financeiro (chatbot) de uma aplicação de extratos. O LLM (Gemini via LangChain create_agent) só escolhe uma consulta fixa e os parâmetros; as consultas calculam com pandas e devolvem só os totais e os dados do gráfico (barras, linha, pizza). Cobre as definições de despesa e receita com estornos, a janela "últimos N meses", períodos explícitos, avisos de cobertura, o prompt de sistema, o histórico da conversa, modelos reserva com timeout curto e os testes sem LLM. Use sempre que for criar ou mudar o chat sobre gastos, as consultas do dashboard, as ferramentas do agente, o prompt do assistente, ou quando o assistente inventar números, errar o período ou demorar.
---

# Camada do agente (`agent/`)

```
agent/
  queries.py     consultas fixas: transações (DataFrame) -> Resultado(dados, grafico). Também o painel.
  assistant.py   ferramentas (@tool), prompt de sistema, histórico, modelos e responde()
  tests/         consultas e ferramentas sem LLM; reserva com um chat model falso
```

## O princípio

**O LLM nunca vê a lista de transações nem faz contas.** Ele escolhe uma ferramenta e os
parâmetros (categoria, quantos meses, período). A ferramenta calcula com pandas e devolve ao LLM
só os totais. O gráfico gerado pela ferramenta vai **direto para o frontend**, sem passar pelo
modelo. O LLM escreve de 1 a 3 frases com os números que recebeu.

Por quê:
- números sempre certos e iguais aos do dashboard (as mesmas funções servem os dois);
- privacidade: o provedor do LLM não recebe a lista de transações;
- respostas rápidas e baratas (poucos tokens; o modelo não precisa raciocinar muito).

## Definições (as mesmas no dashboard e no chat)

- **Despesa**: saída que não é `financeiro` (pagar a fatura, investir ou transferir entre contas
  próprias não é gasto: o gasto já está nas compras do cartão).
- **Estorno casado**: entrada com `meio = estorno`, contraparte igual à de uma compra feita no
  mesmo dia ou antes. Ele ganha a categoria da compra mais recente e **abate** o gasto (`gasto`
  negativo). Um estorno sem compra correspondente fica como receita.
- **Receita**: entrada da categoria `receitas`, menos os estornos casados (senão o estorno
  contaria duas vezes). Totais mensais negativos por causa de estorno aparecem como zero.
- **"Últimos N meses"** terminam no mês da **transação mais recente do usuário**, não no mês de
  hoje: quem enviou extratos até outubro vê junho a outubro, não um novembro vazio.
- **Período explícito**: `de` e `ate` (`AAAA-MM`, inclusivos) trocam os "últimos N meses". Só `de`:
  até o mês mais recente. Só `ate`: os N meses que terminam nele. Máximo de 60 meses por consulta.
- **Cobertura**: se parte do período pedido não tem extrato, o resultado leva um `aviso` ("os
  meses sem extrato aparecem como zero"), para o LLM não dizer que a pessoa não gastou. Se nada
  do período tem extrato: `sem_extrato_no_periodo` + aviso com as datas disponíveis.
- **Rótulos de mês**: `jan/24`, `fev/24`... Período escrito como "jun/24 a nov/24".
- Sem transações → `{"sem_dados": true, "aviso": "O usuário ainda não enviou nenhum extrato."}`.

## Consultas (ferramentas)

| Ferramenta | Parâmetros (padrão) | Dados para o LLM | Gráfico |
|---|---|---|---|
| `gastos_mensais` | `meses=6`, `categoria`, `de`, `ate` | `por_mes`, `total`, `media_mensal`, `periodo` | `barras` |
| `gastos_por_categoria` | `meses=1`, `de`, `ate` | `categorias` (total e %), `total_gasto` | `pizza` |
| `receitas_x_despesas` | `meses=6`, `de`, `ate` | por mês receitas/despesas/saldo e totais | `barras` (2 séries) |
| `evolucao_saldo` | `meses=6`, `de`, `ate` | saldo por mês e acumulado | `linha` (2 séries) |
| `maiores_gastos` | `meses=1`, `quantidade=5` (máx. 20), `categoria`, `de`, `ate` | as N maiores compras (data, estabelecimento, categoria, valor) | `barras_horizontais` |
| `gastos_por_estabelecimento` | `meses=3`, `quantidade=8` (máx. 20), `categoria`, `de`, `ate` | total e nº de compras por estabelecimento | `barras_horizontais` |
| `resumo_do_mes` | `ano`, `mes` (padrão: o mais recente) | receitas, despesas, saldo, 5 maiores categorias | `pizza` |
| `periodo_disponivel` | — | primeira e última data, nº de transações, bancos | nenhum |

`maiores_gastos` é a única que devolve transações individuais (só as N maiores). As outras
devolvem só agregados. `resumo_do_mes` com mês sem ano escolhe o mais recente com aquele mês
("setembro" com dados até mar/25 é set/24).

O **painel** do dashboard usa as mesmas funções: `resumo_do_mes` do mês escolhido (padrão: o
mais recente) para os cartões e `receitas_x_despesas(6, ate=mês)` para o gráfico, mais a lista
de meses disponíveis para o seletor.

Código das consultas: [references/consultas.md](references/consultas.md).

## As ferramentas

- Criadas a cada pergunta por `ferramentas(df, graficos)`, presas ao DataFrame **daquele
  usuário**. O LLM nunca escolhe de quem são os dados.
- O parâmetro `categoria` é tipado com `Literal[...]` das 8 classes: o schema da ferramenta já
  limita o que o LLM pode mandar.
- Um wrapper `roda()` executa a consulta, guarda o gráfico numa lista e devolve só `dados`. Se a
  consulta levanta `ValueError` (mês fora do formato, período invertido), devolve
  `{"erro": "mensagem"}` ao LLM para ele corrigir, porque uma exceção derrubaria a resposta
  inteira.
- A docstring de cada `@tool` é o que o LLM lê para escolher: dê exemplos de perguntas reais
  ("onde gastei mais?", "quanto gastei no iFood em 2024?") e diga quando usar `de`/`ate`.
- Uma resposta tem **um gráfico**: se o agente gerou uma pizza, ela vence (a pergunta era sobre
  divisão); senão, o último gerado.

## Prompt de sistema (resumo)

Texto completo em [references/prompt-e-agente.md](references/prompt-e-agente.md). Regras que ele
impõe:

1. Responder em português do Brasil.
2. Para QUALQUER número, chamar uma ferramenta; nunca inventar nem calcular.
3. Não descrever o gráfico ponto a ponto (ele já aparece na tela), e sim comentar o que importa.
4. Divisão entre categorias → `gastos_por_categoria` (pizza); evolução mês a mês →
   `gastos_mensais`.
5. No máximo uma ferramenta por pergunta, salvo se a pergunta pede duas coisas.
6. Como mapear "em 2024", "de março a junho", "desde janeiro" para `de`/`ate`; dizer sempre o
   período usado.
7. O período dos extratos vai **no fim do prompt** (`contexto_dos_dados`): o modelo nunca deve
   dizer que não há dados de um período que está dentro dele. Repassar o `aviso`; corrigir
   parâmetros se vier `erro`.
8. O que cada categoria contém; "comida" sem dizer onde → `alimentacao_fora`, avisando que
   mercado é separado; "despesa" não inclui `financeiro`.
9. Sem dados → dizer que é preciso importar um extrato.
10. Fora do assunto (finanças do usuário) → não responder o conteúdo; dizer educadamente o que
    sabe fazer e sugerir uma pergunta.
11. Ser breve: 1 a 3 frases, valores no formato R$ 1.234,56.

## Histórico da conversa

- Vão como contexto as **últimas 12 mensagens**, só o texto (`HumanMessage`/`AIMessage`).
- O gráfico **não** entra no histórico. Uma nota como "[gráfico mostrado: ...]" era imitada pelo
  modelo nas respostas seguintes. O texto da resposta já diz o assunto e o período, o que basta
  para "e com transporte?".
- Por segurança, a resposta final passa por uma limpeza que tira notas entre colchetes sobre
  gráfico, caso o modelo invente uma.

## Modelo, velocidade e falhas

- `langchain.agents.create_agent(model, tools, system_prompt, middleware)` e
  `invoke({"messages": [...]}, config={"recursion_limit": 8})`. O texto final é
  `saida["messages"][-1].text`. Vazio → "Não consegui responder agora. Tente reformular a
  pergunta."
- `ChatGoogleGenerativeAI(model, api_key, temperature=0, max_retries=0, timeout=10)`.
- **Raciocínio mínimo** (`thinking_level="minimal"`; nos modelos 2.x, `thinking_budget=0`). O
  raciocínio longo fazia algumas respostas levarem ~30 s; com ele mínimo, ~1,6 s e as mesmas
  respostas. A tarefa é só escolher uma ferramenta e resumir números prontos.
- **Sem novas tentativas no mesmo modelo** (`max_retries=0`): modelo sobrecarregado (503 "high
  demand") não melhora repetindo. Quem tenta de novo é o próximo modelo da lista, via
  `ModelFallbackMiddleware(*reservas)`, cada um com o mesmo timeout curto. O principal e os
  reservas vêm do `.env` (`GEMINI_MODEL`, `GEMINI_MODELOS_RESERVA`, `GEMINI_TIMEOUT`).
- Os modelos são criados uma vez por processo (dependência da API). O LangChain só é importado
  quando o chat é usado pela primeira vez.
- Qualquer exceção de `responde` vira 502 na API, e nada é gravado.
- Para trocar de provedor, troque só a função que cria o chat model por outro do LangChain, com
  as mesmas regras: temperatura 0, timeout curto, sem novas tentativas e com reservas.

## Testes (sem LLM)

- Cada consulta com um DataFrame inventado: janela que termina no último mês, `de`/`ate`, aviso
  de cobertura, estorno abatendo a compra (e não contando como receita), despesa sem
  `financeiro`, mês sem ano, painel com mês escolhido.
- Ferramentas: os 8 nomes; `dados` sem `grafico`; o gráfico vai para a lista; `categoria` só
  aceita as 8 classes (confira no schema); parâmetro inválido volta como `{"erro"}` sem gráfico.
- Histórico vira mensagens só com o texto; limpeza das notas de gráfico; contexto com o período.
- `escolhe_grafico`: a pizza tem prioridade.
- Reserva: um `BaseChatModel` falso que levanta "503 UNAVAILABLE" como principal e outro que
  responde como reserva → a resposta vem do reserva e o principal foi chamado uma vez só. Sem
  reserva, o erro sobe.
- Um teste manual com o LLM de verdade (fora do `pytest`) para conferir as perguntas de exemplo.
