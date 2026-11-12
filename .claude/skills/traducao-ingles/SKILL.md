---
name: traducao-ingles
description: Boas práticas para traduzir o código Python deste projeto do português para o inglês (pastas, arquivos, funções, variáveis, classes, comentários) sem alterar o esquema do banco, o contrato da API, as colunas do modelo de ML nem o frontend. Usar sempre que for renomear qualquer parte do código para inglês.
---

# Tradução do código para inglês

Objetivo: o código Python passa a ser escrito em inglês **sem mudar comportamento**. O banco de
dados, o contrato da API (rotas e JSON), os dados do modelo de ML e o **frontend** continuam
exatamente como estão.

## Como trabalhar

1. Trabalhe num branch próprio (ex.: `refactor/ingles`), nunca direto na `main`.
2. Antes de começar, rode a checagem final (abaixo) e anote o resultado: é a linha de base.
3. Um módulo por vez, nesta ordem: `extraction/` → `ml/` → `database/` → `agent/` → `api/`.
   O `frontend/` está fora da tradução.

## Situação atual (2026-11-12)

A tradução foi **encerrada por decisão do usuário** depois de `ml/`:
- Feito: estrutura de pastas e arquivos (todos os módulos Python), pacote `statement`,
  conteúdo de `extraction/` e de `ml/`.
- Não traduzido (de propósito): o **conteúdo** de `database/`, `agent/` e `api/` (nomes de
  funções, variáveis, comentários). Só os nomes de pastas e arquivos deles estão em inglês.
- Não retome os módulos restantes sem o usuário pedir. Se pedir, siga as regras abaixo.
4. Apresente ao usuário o plano de cada módulo antes de editar e espere a confirmação.
5. Renomeie por tokens, não por texto: um script com `tokenize` troca só nomes de código e nunca
   toca em strings, regex ou textos dos PDFs. Antes de aplicar, verifique colisões (nome novo que
   já existe no arquivo).
6. Para cada nome renomeado, procure também as ocorrências **como texto** (`grep -rn`): strings de
   `monkeypatch`, `parametrize("a,b")`, `dest=` do argparse, notebooks, README.
7. Ao fim de cada módulo: checagem final sem erros → um commit só daquele módulo.
8. Não misture tradução com mudança de comportamento, refatoração ou correção de bug.

## O que traduzir

- Nomes de pastas e arquivos Python (já feito para a estrutura: `agent/`, `database/`,
  `extraction/`, `api/routes/`, `api/services/`, `ml/train.py`...).
- Nomes de funções, métodos, variáveis, parâmetros internos, constantes, classes e tipos.
- Comentários e docstrings.
- Python: `snake_case` para funções/variáveis, `PascalCase` para classes, `UPPER_CASE` para constantes.

## O que NÃO traduzir (fica como está)

### Frontend
- Nada em `frontend/`: nem arquivos, nem componentes, nem tipos. Por isso o contrato da API
  (abaixo) não pode mudar.

### Banco de dados
- Os arquivos `.sql` em `database/migrations/`, inclusive os **nomes dos arquivos** (ficam
  gravados em `public.migracoes_aplicadas`; renomear faz a migração rodar de novo).
- Nomes de tabelas, colunas, funções SQL (`cria_perfil_do_usuario`, `atualiza_conversa`) e valores
  de `CHECK`. Strings SQL no código continuam com esses nomes.
- Chaves dos dicts que vêm do banco (são os nomes das colunas).

### Contrato da API
- **Campos** dos modelos Pydantic em `api/schemas.py` (viram o JSON). O nome da **classe** pode
  ser traduzido (`ExtratoEnviado` → `UploadedStatement`).
- Rotas (`/extratos`, `/transacoes`, `/conversas`, `/painel`, `/chat`...).
- Parâmetros de funções de rota: o FastAPI usa o nome do parâmetro como nome do campo de
  query/path/form. Para traduzir, use alias e mantenha o nome público:
  ```python
  start: Annotated[date | None, Query(alias="inicio")] = None
  statement_id: Annotated[UUID, Path(alias="extrato_id")]
  ```
- Campos que viram JSON por `asdict`/`model_dump` (ex.: `FileReport` do pipeline vira `relatorio`).
- Códigos devolvidos em texto: motivos de rejeição (`FormatoNaoReconhecido`,
  `LayoutInesperado:...`), status (`aceito`, `ok`, `sem_totais`). Se o código vinha do nome de uma
  classe (`type(exc).__name__`), dê à classe um atributo fixo (`code = "FormatoNaoReconhecido"`) e
  use o atributo, para poder traduzir a classe.
- Nomes de parser (`bradesco_conta_pdf`...): gravados na coluna `extratos.parser` e lidos pelo
  frontend. Os arquivos dos parsers têm esse mesmo nome e também ficam.
- Chaves dos dicts que o agente devolve para o JSON (`/painel`, gráficos): `tem_dados`, `mes`,
  `receitas`...
- Mensagens de erro de `HTTPException` e todo texto que o usuário vê.

### Modelo de ML e dados
- Valores de `COLUMNS` e campos de `OutputRow` (`extraction/src/statement/models.py`):
  `id_usuario`, `data`, `historico`, `contraparte`, `valor`, `tipo`, `meio`, `banco`. O `.pkl` procura
  as colunas por nome. Essas palavras ficam em português também como nomes de atributo/variável
  onde representam esses campos.
- Valores dos enums (`"entrada"`, `"saida"`, `"pix"`, `"mercado"`...). O nome do enum e dos membros
  pode ser traduzido (`TransactionType.INCOME = "entrada"`).
- Pastas e arquivos de dados locais (fora do git, cada colega tem os seus): `data/privado/`,
  `data/raw/`, `data/saida/`, `ml/dados/`, `ml/modelos/svm_tfidf.pkl`, e os nomes dos arquivos
  gravados neles (`revisar.csv`, `historicos_desconhecidos.csv`...).
- Pasta `dados/` dentro do pacote `statement` (listas públicas usadas por `files("statement")`).

### Interface de linha de comando e ambiente
- Flags e mensagens das CLIs (`--entrada`, `--saida`, `--privado`, `extrair`, `tudo`): o código
  interno usa `dest=` em inglês (`args.source`).
- Variáveis de ambiente (`.env`).

## Pontos que quebram em silêncio (conferir sempre)

1. **Notebooks** (`ml/*.ipynb`): decisão do usuário: só os **imports** mudam, com alias para
   o código das células continuar igual (`from ml.train import build_model as monta_modelo`,
   `from ml.train import train_model as treina`). Código das células, saídas e markdown ficam
   como estão (markdown em português, como os READMEs): os notebooks não rodam sem o CSV rotulado
   e a última célula do `champion_model` regrava o `.pkl`. Confira que o JSON continua válido.
   Nenhum teste avisa.
2. **Strings nos testes**: `monkeypatch.setattr(config, "CAMINHO_MODELO", ...)`,
   `monkeypatch.setattr("api.rate_limit.time.monotonic", ...)` e `parametrize("nome,esperado")`
   usam nomes como texto. Se o atributo for renomeado e a string não, o teste usa o recurso real
   ou quebra.
3. **Módulos usados como objeto** (`from api import cipher` → `cipher.cifra(...)`;
   `from agent import queries` → `queries.tabela(...)`): renomear o módulo exige trocar os usos
   no arquivo. Cuidado com nomes iguais que são variáveis (`limite = Limite(...)`) ou atributos
   (`self.extratos`).
4. **Prompt do agente** (`agent/assistant.py`): o texto cita as ferramentas pelo nome
   (`gastos_por_categoria`, `gastos_mensais`, `resumo_do_mes`...). Renomeie as funções `@tool` e
   o prompt juntos.
5. **Comandos documentados**: `python -m statement`, `python -m ml.label`, `python -m ml.train`,
   `python -m database.migrate`, `python -m api.retrain`, `python -m api.cipher`,
   `uvicorn api.main:app`. Se um módulo mudar de nome, atualize README.md, `ml/README.md`,
   `extraction/README.md`, os `prog=` do argparse e mensagens que citam comandos.
6. **Mocks e falsos** (`api/tests/fakes.py`): os métodos do banco falso precisam acompanhar os
   novos nomes do `database/repository.py`.
7. **Não execute scripts para "testar"**: `python -m api.retrain` não lê argumentos e roda o
   retreino de verdade contra o banco do `.env`. Para conferir comandos, use `--help` só nos que
   usam argparse (`statement`, `ml.label`, `ml.train`, `database.migrate`).
8. **Pacote instalado**: o pacote é `statement` (instalado em modo editável). Depois de renomear
   o pacote ou mover a pasta, rode `pip install -e .` e desinstale o nome antigo.

## Glossário (use sempre o mesmo termo)

| pt | en |
|---|---|
| extrato | statement |
| transacao / transacoes | transaction / transactions |
| lancamento | entry |
| fatura | invoice |
| titular / portador | holder / cardholder |
| usuario | user |
| conversa / mensagem | conversation / message |
| pergunta / resposta | question / answer |
| categoria / categoriza | category / categorize |
| consulta / consultas | query / queries |
| gravacao / grava | save_result / save (`write` quando é arquivo) |
| lista_ / busca_ / apaga_ / cria_ | list_ / find_ / delete_ / create_ |
| carrega_ / monta_ / treina / rotula | load_ / build_ / train / label |
| executa / executa_tudo | run / run_all |
| periodo / inicio / fim | period / start / end |
| receitas / despesas / gastos | income / expenses / spending |
| saldo | balance |
| meio (de pagamento) / tipo | payment method / transaction type |
| painel | dashboard |
| assistente / ferramentas / agente | assistant / tools / agent |
| banco (pasta/módulo do BD) | database |
| conta (do usuário) / saude | account / health |
| autenticacao / dependencias / esquemas / limite | auth / dependencies / schemas / rate_limit |
| anonimizacao / normalizacao | anonymization / normalization |
| reconciliacao / validacao | reconciliation / validation |
| estabelecimento | merchant |
| relatorio | report |
| vazamento | leak |
| retreino / retreinar | retraining / retrain |
| cifra | cipher |
| falsos (testes) | fakes |

Termo fora da tabela: escolha um, use igual em todo o projeto e acrescente aqui.

## Checagem final (depois de cada módulo)

```bash
# na raiz, com o venv ativo
pytest
python -c "import api.main"           # a API importa sem erro
python -m statement --help            # CLIs com argparse respondem
python -m ml.label --help
python -m ml.train --help
python -m database.migrate --help
```

Depois de `ml/` (e no fim de tudo):
- Execute `ml/champion_model.ipynb` do início ao fim (`jupyter nbconvert --to notebook --execute`
  ou pelo editor), sem gravar por cima do `.pkl` se não for a intenção.
- Confira que o `.pkl` carrega e categoriza: `joblib.load("ml/modelos/svm_tfidf.pkl").predict(...)`
  com um DataFrame de `COLUMNS`.

No fim de tudo: suba API e frontend e teste à mão login, importar e excluir extrato, aba Extrato,
dashboard e assistente.
