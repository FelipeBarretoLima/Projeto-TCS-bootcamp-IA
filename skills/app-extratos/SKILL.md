---
name: app-extratos
description: Arquitetura, contratos e plano de construção de uma aplicação web que importa extratos bancários (PDF/CSV), extrai as transações com um parser por formato, anonimiza, categoriza com ML, guarda no Supabase e responde perguntas sobre os gastos com um assistente LLM (dashboard + chat). Use sempre que alguém quiser criar, recriar, planejar ou entender uma aplicação de finanças pessoais a partir de extratos, mesmo sem dizer "arquitetura", e antes de começar qualquer camada. Ela define a ordem de construção e qual skill de camada usar em cada fase (app-extratos-extracao, -ml, -banco, -api, -agente, -frontend).
---

# Aplicação de extratos bancários: arquitetura e plano

Esta skill descreve a aplicação inteira e como construí-la do zero, uma camada por vez. Ela foi
escrita a partir de um projeto real, o **TAS (Transactions Assistancy Service)**, que serve de
referência: os nomes, contratos e decisões abaixo vêm dele e foram testados.

## O que a aplicação faz

1. A pessoa cria uma conta e entra (Supabase Auth).
2. Envia um extrato em PDF ou CSV (conta corrente ou fatura de cartão).
3. A API descobre o formato, extrai os lançamentos, confere a soma com os totais declarados no
   próprio documento, anonimiza e valida. O arquivo é apagado; só as transações ficam.
4. Cada transação ganha uma categoria (entrada = `receitas` por regra; saída = modelo de ML) e é
   gravada na conta da pessoa, sem duplicar o que já veio de outro extrato.
5. A aba **Extrato** lista, filtra, exporta e deixa corrigir a categoria; as correções retreinam
   o modelo.
6. O **Dashboard** mostra receitas, despesas e saldo do mês e um gráfico. O **assistente** responde
   perguntas ("onde gastei mais?") com números calculados por consultas fixas, nunca pelo LLM.

## Camadas

| Fase | Pasta | Responsabilidade | Tecnologia | Skill |
|---|---|---|---|---|
| 1 | `extraction/` (pacote `statement`) | arquivo do banco → linhas padronizadas e anônimas | Python 3.12, pdfplumber, pydantic | `app-extratos-extracao` |
| 2 | `ml/` | linha → categoria (8 classes) | scikit-learn (TF-IDF + SVM linear) | `app-extratos-ml` |
| 3 | `database/` | tabelas, migrações, acesso, deduplicação | PostgreSQL no Supabase, psycopg 3 | `app-extratos-banco` |
| 4 | `api/` | HTTP: login, importação, transações, painel, chat | FastAPI | `app-extratos-api` |
| 5 | `agent/` | pergunta → consulta fixa → texto + gráfico | LangChain + Gemini, pandas | `app-extratos-agente` |
| 6 | `frontend/` | páginas web | React + TypeScript + Vite, Recharts | `app-extratos-frontend` |

As dependências só descem: a API usa todas as outras camadas; o ML usa o contrato da extração;
banco, agente e frontend não importam nada da extração.

## Fluxo dos dados

```
navegador ──login──> Supabase Auth ──token──> navegador
    │
    │ POST /api/extratos (arquivo + Authorization: Bearer <token>)
    ▼
api ── pasta temporária ──> statement.pipeline.run
         detecta o formato → extrai → confere totais → anonimiza → valida
    ◀── linhas anônimas + texto original (só em memória)
    ├─ categoria: entrada = receitas (regra); saída = modelo .pkl
    ├─ texto original → cifrado (Fernet) antes de gravar; o arquivo é apagado
    └─ grava no Postgres (sem repetir transações de extratos sobrepostos)

dashboard / chat ──> api ──> agent.queries (pandas) ──> totais + dados do gráfico
                              └─ chat: o LLM escolhe a consulta e escreve 1 a 3 frases
correção de categoria ──> api ──> a cada 15 correções, retreino em segundo plano
```

## Regras que valem em todas as camadas

Explique estas regras ao usuário quando forem relevantes; elas são o que torna a aplicação
confiável com dados bancários reais.

**Privacidade primeiro**
- Extratos reais e tudo o que deriva deles ficam fora do git (`data/`, `ml/dados/`, `ml/modelos/`).
  Fixtures de teste são sempre inventadas: nunca copie conteúdo de extrato real para um teste.
- O arquivo enviado é processado numa pasta temporária, com nome fixo, e apagado no fim.
- A anonimização é determinística, e um validador varre a saída antes de gravar: se achar um padrão
  de dado pessoal, nada é gravado. Na dúvida, a linha vai para revisão privada, não para a saída.
- O texto original (sem anonimizar) só volta para o dono. No banco ele fica cifrado com uma chave
  do `.env`. ML, chat e treino usam só o texto anonimizado.
- O LLM nunca vê a lista de transações nem faz contas.
- Exceções, logs e respostas de erro levam só códigos, nunca trechos do extrato.

**Determinismo e transparência**
- Um parser por formato, com regex explícitas. Linha que ele não conhece é motivo para rejeitar o
  arquivo, com um código que diz por quê. Nunca "adivinhe" o layout.
- Todo arquivo é conferido contra os totais que o próprio documento declara.
- A tela explica por que um arquivo foi rejeitado e o que fazer em seguida.

**Contratos fixos**
- Os mesmos nomes e valores no parser, CSV, ML, banco, API, agente e frontend. Detalhes em
  [references/contratos.md](references/contratos.md).
- Escreva testes que comparam as camadas, por exemplo os valores dos `CHECK` do SQL contra os
  enums do Python.

**Dinheiro e datas**
- `Decimal` no Python, `numeric(12, 2)` no banco e texto no JSON das transações (`"-12.50"`).
  `float` só em totais agregados do painel e dos gráficos.
- Datas como `AAAA-MM-DD`; no frontend, formate sem passar por `Date`, para não sofrer com o fuso.

**Testes sem internet**
- Banco, login e LLM trocados por falsos nos testes. Testes contra o banco real só com uma variável
  de ambiente (`TESTE_BANCO=1`), dentro de uma transação desfeita no fim.

**Segredos**
- Só no `.env` da raiz, fora do git. Nunca cole o conteúdo do `.env` num chat.

## Contratos (resumo)

- Linha do parser (CSV): `id_usuario,data,historico,contraparte,valor,tipo,meio,banco`.
- `tipo`: `entrada` | `saida`, coerente com o sinal do valor.
- `meio`: `pix`, `ted_doc`, `boleto`, `cartao_debito`, `cartao_credito`, `pagamento_fatura`,
  `tarifa`, `juros_iof`, `investimento`, `rendimento`, `salario`, `saque`, `estorno`,
  `transferencia_interna`, `outros`.
- `contraparte`: nome da empresa anonimizado, `PESSOA_FISICA` quando é uma pessoa, ou vazio.
- Categorias: `mercado`, `alimentacao_fora`, `transporte`, `compras`, `contas_servicos`,
  `transferencia_pessoa`, `receitas`, `financeiro`. Sem categoria = `null`.
- Origem da categoria: `regra`, `mapa`, `modelo`, `usuario`.
- Gráfico: `{"tipo": "barras" | "barras_horizontais" | "linha" | "pizza", "titulo", "rotulos",
  "series": [{"nome", "valores"}], "formato": "moeda"}`, gerado pelo agente e desenhado pelo
  frontend.

## Estrutura do repositório

```
.env                     segredos (fora do git)
.gitignore
pyproject.toml           pacote statement + configuração do pytest
requirements.txt
README.md                como rodar
extraction/              src/statement/ (parser) + tests/
ml/                      classes.py, label.py, train.py, retrain.py, notebooks, tests/
database/                migrations/*.sql, migrate.py, connection.py, repository.py, deduplication.py, tests/
api/                     main.py, config.py, auth.py, ..., routes/, services/, tests/
agent/                   queries.py, assistant.py, tests/
frontend/                package.json, vite.config.ts, src/
data/                    extratos reais e saídas (fora do git): raw/, saida/, privado/
```

`.gitignore` mínimo: `.venv/`, `.env`, `__pycache__/`, `.pytest_cache/`, `data/`, `*.egg-info/`,
`ml/dados/`, `ml/modelos/`, e no frontend `node_modules` e `dist`.

`pyproject.toml` da referência:

```toml
[build-system]
requires = ["setuptools"]
build-backend = "setuptools.build_meta"

[project]
name = "statement"
version = "0.1.0"
requires-python = ">=3.12,<3.13"

[tool.setuptools.packages.find]
where = ["extraction/src"]

[tool.setuptools.package-data]
statement = ["dados/*.txt"]

[tool.pytest.ini_options]
testpaths = ["extraction/tests", "ml/tests", "api/tests", "database/tests", "agent/tests"]
pythonpath = ["extraction/src", "."]
```

`requirements.txt` (versões fixas; o `.pkl` só carrega com a mesma versão do scikit-learn):
`pdfplumber`, `pandas`, `pydantic`, `python-dotenv`, `cryptography`, `pytest`, `scikit-learn`,
`matplotlib`, `ipykernel`, `fastapi`, `uvicorn[standard]`, `python-multipart`, `httpx`,
`psycopg[binary,pool]`, `langchain`, `langchain-google-genai` e, na última linha, `-e .` (instala o
pacote `statement` em modo editável). Se a pasta ou o pacote mudar de nome, rode `pip install -e .`
de novo.

## Ordem de construção

Construa uma camada por vez, nesta ordem. Antes de cada fase, carregue a skill da camada, mostre
ao usuário o plano daquela camada e espere a confirmação. Só passe para a próxima quando o
critério "pronto quando" for cumprido.

| Fase | O quê | Pronto quando |
|---|---|---|
| 0. Preparação | repositório, `.gitignore`, venv com Python 3.12, `requirements.txt`, `pyproject.toml`, README | `pytest` roda (mesmo sem testes) |
| 1. Extração | modelos, normalização, anonimização, validador, pipeline, CLI e um parser por formato. Comece pelo formato mais simples (o CSV da conta do Nubank não tem PDF nem totais) | `python -m statement extrair ...` aceita um extrato real do usuário e os testes com dados inventados passam |
| 2. ML | rotulagem (regras + mapa de estabelecimentos), comparação de modelos, treino, `.pkl` | `python -m ml.train` gera o `.pkl` e há métricas com validação por usuário |
| 3. Banco | projeto no Supabase, `DATABASE_URL` no `.env`, migrações, repositório, deduplicação | `python -m database.migrate` cria as tabelas e os testes passam |
| 4. API | rotas, login, importação, transações, painel, chat, limites, cifra | `uvicorn api.main:app --reload` sobe, `/docs` abre e os testes com falsos passam |
| 5. Agente | consultas fixas e assistente | testes das consultas e ferramentas sem LLM passam e uma pergunta real responde |
| 6. Frontend | login, importar, extrato, dashboard com chat, conta | `npm run build` sem erros e os fluxos funcionam no navegador |
| 7. Publicação | `npm run build` servido pela própria API | a página abre em `http://localhost:8000` e o link de recuperar senha funciona |

As fases 1 e 2 dependem de extratos reais do usuário, que ficam só na máquina dele. Sem eles, dá
para fazer as fases 3 a 6 com o parser de um formato e sem modelo: as saídas ficam sem categoria
até existir um `.pkl`.

## Antes de começar, pergunte ao usuário

- **Bancos e produtos.** Quais bancos, se é conta ou cartão, e se o arquivo é PDF ou CSV. Ele
  precisa ter um extrato real de cada formato na máquina dele (em `data/raw/<n>/`, nunca no git)
  para você conhecer o layout.
- **Dados para treinar.** Quantas pessoas vão fornecer extratos. O modelo precisa de dados de
  várias pessoas; com uma só, a validação por usuário não existe.
- **Categorias.** A referência usa 8 categorias. Mudar a lista muda o ML, o `CHECK` do banco, o
  prompt do agente e o frontend.
- **Serviços.** Conta no Supabase (Postgres + Auth) e chave do LLM (Gemini pelo AI Studio, na
  referência).
- **Identidade.** Nome do produto, cores e logotipo. A referência tem um design system próprio
  (ver `app-extratos-frontend`).

## Arquivo `.env` (raiz)

| Variável | Para quê |
|---|---|
| `DATABASE_URL` | Supabase > Connect > **Session pooler** > URI, com a senha no lugar de `[YOUR-PASSWORD]` |
| `SUPABASE_PUBLISHABLE_KEY` | Supabase > Project Settings > API Keys > Publishable key (`sb_publishable_...`) |
| `SUPABASE_URL` | opcional: a API deduz `https://<ref>.supabase.co` do usuário `postgres.<ref>` do `DATABASE_URL` |
| `GEMINI_API_KEY` | chave do LLM do assistente |
| `GEMINI_MODEL`, `GEMINI_MODELOS_RESERVA`, `GEMINI_TIMEOUT` | opcionais: modelo principal, reservas em ordem e segundos de espera por modelo |
| `CHAVE_ORIGINAIS` | chave Fernet que cifra o texto original (`python -m api.cipher --nova-chave`). A mesma em toda a equipe; perdê-la = os originais gravados não abrem mais |
| `CORS_ORIGENS` | opcional: só se a página ficar num domínio diferente do da API |

## Comandos da aplicação pronta

```bash
python -m statement tudo            # extratos de data/raw/ -> data/saida/transacoes.csv
python -m ml.label                  # CSV do parser -> ml/dados/transacoes_rotuladas.csv
python -m ml.train                  # CSV rotulado -> ml/modelos/svm_tfidf.pkl
python -m database.migrate          # cria/atualiza as tabelas (--status só lista)
uvicorn api.main:app --reload       # API em :8000 (documentação em /docs)
cd frontend && npm run dev          # página em :5173 (repassa /api para :8000)
pytest                              # todos os testes, sem internet
```

## Convenções de código

- Python 3.12, tipado, `from __future__ import annotations`, docstrings que explicam o porquê.
- Na referência, pastas e módulos têm nomes em inglês (`extraction`, `database`, `agent`...). O
  código de `extraction/` e `ml/` está em inglês, e o de `database/`, `api/`, `agent/` e
  `frontend/` em português. Numa aplicação nova, escolha uma língua para os nomes de código e use
  em tudo.
- Contratos de dados (colunas, campos JSON, valores de enum) e textos da interface ficam em
  português, iguais em todas as camadas.
- Cada decisão tomada com o usuário vira um comentário com a data
  (`# decisão do usuário em AAAA-MM-DD`), para ninguém "corrigir" depois sem saber.
- Um commit por mudança coerente; nunca misture refatoração com mudança de comportamento.

## Checagem final de ponta a ponta

1. `pytest` passa sem internet.
2. Criar conta → entrar → importar um extrato real → o resumo mostra "Totais conferidos" e a
   tabela mostra ao dono o texto original. No banco, `historico` e `contraparte` estão
   anonimizados e o original só existe cifrado.
3. Importar o mesmo arquivo de novo → recusado (409). Importar um extrato com período sobreposto
   → as transações repetidas não entram duas vezes.
4. Aba Extrato: filtrar por período e categoria, corrigir uma categoria e exportar CSV.
5. Dashboard: trocar o mês; perguntar "onde gastei mais?" → texto curto + gráfico de pizza.
6. Excluir o extrato → as transações dele somem. Excluir a conta → tudo some (LGPD).
7. Nenhum dado real no `git status` (nem notebooks com saídas).
