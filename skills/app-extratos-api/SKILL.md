---
name: app-extratos-api
description: Como construir a API FastAPI de uma aplicação de extratos bancários. Cobre login com token do Supabase Auth validado no servidor, importação de extrato (upload, pasta temporária, pipeline do parser, categoria por regra + ML, gravação deduplicada, 409/422), aba de transações com filtros e correção de categoria que dispara retreino em segundo plano, painel do mês, chat com o assistente, conta (LGPD), limite de uso por usuário, cifra Fernet do texto original, contrato Pydantic com o frontend e testes com banco e login falsos. Use sempre que for criar ou mudar rotas, autenticação, upload, schemas, erros HTTP, rate limit, CORS, a publicação do frontend pela API ou os testes da API.
---

# Camada da API (`api/`)

FastAPI que junta as outras camadas: extração (`statement`), ML (`.pkl`), banco (`database`) e
agente (`agent`). O frontend só fala com ela, sempre em `/api/...`.

```
api/
  main.py            app, routers sob /api, ciclo de vida, CORS, página compilada
  config.py          .env e caminhos (modelo, CSV base, data/privado, frontend/dist), limites
  auth.py            Usuario atual a partir do token do Supabase (cache de 60 s)
  dependencies.py    banco() por requisição e o modelo do assistente (criado uma vez)
  rate_limit.py      limite por usuário em memória (chat e importação)
  cipher.py          Fernet para o texto original (python -m api.cipher --nova-chave)
  schemas.py         modelos Pydantic das respostas (contrato com o frontend)
  retrain.py         python -m api.retrain [--historico]
  routes/            health, statements (extratos), transactions, assistant, account
  services/          extraction (ponte com o parser), categorization, retraining
  tests/             conftest.py (falsos automáticos), fakes.py (BancoFalso), um arquivo por rota
```

## Decisões (e por quê)

- **Login no navegador, conferido no servidor.** O frontend entra com `supabase-js` e manda
  `Authorization: Bearer <access_token>`. A API pergunta ao Supabase de quem é o token
  (`GET {SUPABASE_URL}/auth/v1/user`, com o header `apikey`) e guarda a resposta por **60 s** num
  cache (que é limpo se passar de 1000 entradas), para não consultar a cada clique. O logout
  (`DELETE /api/sessao`) tira o token do cache na hora.
- **Configuração pública por rota.** `GET /api/config` devolve a URL do Supabase e a chave
  *publishable*, feita para ficar no navegador. Assim o frontend não precisa de um `.env` próprio.
  A chave secreta nunca sai do servidor.
- **Uma transação por requisição**: `banco()` é uma dependência com `yield` sobre
  `conexao(DATABASE_URL)`. Se a rota der erro, nada fica gravado. Sem `DATABASE_URL` → 503 com a
  instrução.
- **Rotas síncronas (`def`) para trabalho pesado** (extração, ML, chat): o FastAPI roda cada uma
  numa thread à parte e não trava o loop.
- **O arquivo enviado não toca o disco do projeto.** Vai para um `TemporaryDirectory` com nome
  fixo (`extrato.pdf`), porque o nome original pode ter dado pessoal. Depois de rodar o pipeline,
  os caches de leitura do parser são limpos.
- **Categoria na importação**: entrada → `receitas` (origem `regra`); saída → modelo `.pkl`
  (origem `modelo`). O modelo é recarregado sozinho quando o arquivo muda (cache pela data de
  modificação). Sem `.pkl`, as saídas ficam sem categoria.
- **Texto original cifrado**: a importação devolve ao dono `historico_original` e
  `contraparte_original`, e grava no banco só `original_cifrado` (Fernet com `CHAVE_ORIGINAIS`).
  A aba Extrato decifra para o dono. Sem chave, nada original é gravado. Chave diferente →
  mostra o anonimizado e registra um aviso.
- **Erros em português, sem conteúdo do extrato**: `HTTPException(status, "mensagem")` vira
  `{"detail": "mensagem"}`, que o frontend mostra como está.
- **Limite de uso por usuário** (janela deslizante em memória, por processo): 10 perguntas por
  minuto e 20 importações a cada 10 minutos → 429 "espere N s".
- **Retreino em segundo plano**: a correção de categoria faz `commit` na hora e chama
  `dispara_se_preciso`. Esse passo nunca pode atrapalhar a correção: qualquer falha nele só vai
  para o log.
- **Um único servidor para publicar**: com `frontend/dist/index.html` presente, a API serve
  `/assets` e devolve `index.html` para qualquer rota que não seja `/api/...` (rotas do React).
  Arquivos soltos só se estiverem dentro de `dist` (`is_relative_to`, contra path traversal).
  CORS só se `CORS_ORIGENS` estiver no `.env`.

## Rotas

| Rota | Faz | Erros |
|---|---|---|
| `GET /saude` | `{"status": "ok"}` | |
| `GET /config` | `{"supabase_url", "supabase_publishable_key"}` | |
| `DELETE /sessao` | esquece o token (logout) | |
| `POST /extratos` | multipart `arquivo` (+ `usuario` opcional, pseudônimo `uNN`, padrão `u01`) → `ResultadoImportacao` | 400 formato/tamanho/vazio, 409 repetido, 422 vazamento, 429, 500 chave inválida |
| `GET /extratos` | extratos importados, do mais recente | |
| `DELETE /extratos/{id}` | 204 | 404 |
| `GET /transacoes/periodo` | `primeira`, `ultima`, `padrao_inicio`, `padrao_fim` (6 meses até o mês da última) | |
| `GET /transacoes?inicio&fim&categoria` | `TransacaoSalva[]` (mais recente primeiro; `categoria=sem_categoria` filtra as nulas) | 400 período invertido ou categoria inválida |
| `PATCH /transacoes/{id}` | `{"categoria": "mercado" \| null}` → 204; pode disparar retreino | 400, 404 |
| `GET /painel?mes=AAAA-MM` | cartões do mês e gráfico receitas x despesas de 6 meses | 400 mês inválido |
| `GET /conversas` | conversas, da mais recente | |
| `GET /conversas/{id}/mensagens` | mensagens em ordem | 404 |
| `PATCH /conversas/{id}` | `{"titulo"}` (1 a 60) → 204 | 400, 404 |
| `DELETE /conversas/{id}` | 204 | 404 |
| `POST /chat` | `{"mensagem" (1 a 1000), "conversa_id" \| null}` → `RespostaChat` | 404, 429, 502 assistente falhou, 503 sem chave |
| `PATCH /perfil` | `{"nome"}` (1 a 80) → `{"nome", "email"}` | 400 |
| `DELETE /conta` | apaga o login e tudo em cascata → 204 | |

Todas sob o prefixo `/api`; todas, menos `saude`, `config` e `sessao`, exigem login (401
"faça login para continuar" / "sessão expirada: faça login de novo"). Schemas completos em
[references/rotas-e-esquemas.md](references/rotas-e-esquemas.md).

## Fluxo da importação (`POST /api/extratos`)

1. Limite de importação do usuário; pseudônimo `u\d{2}`.
2. Extensão `.pdf` ou `.csv` (do nome enviado); lê no máximo `TAMANHO_MAXIMO + 1` bytes (10 MB)
   para recusar arquivo grande sem ler tudo; vazio → 400.
3. `processa_extrato(conteudo, extensao, pseudonimo)`: pasta temporária, `statement.pipeline.run`
   com as pessoas declaradas nos mapas privados (`declared_people(DIR_PRIVADO)`, só leitura). Se
   houve vazamento → 422 "possível dado pessoal detectado na saída: nenhuma transação foi
   devolvida".
4. `categoriza(resultado)`: regra + modelo; conta `sem_categoria`.
5. Se o relatório diz `aceito` e há transações: `garante_usuario`, `grava_extrato` com o sha256 do
   conteúdo, o nome do arquivo (até 200 caracteres), parser, período e as transações (campos
   anonimizados + `original_cifrado`). `ExtratoRepetido` → 409 "este arquivo já foi importado".
6. Resposta: relatório + transações (com os originais, para o dono ver) + `gravacao`
   (`extrato_id`, `gravadas`, `repetidas`), ou `gravacao: null` se o arquivo foi rejeitado.

Um arquivo rejeitado responde **200** com `relatorio.status = "rejeitado"` e o `motivo`. A
rejeição é um resultado do processamento, não um erro HTTP, e o frontend explica o motivo.

## Fluxo do chat (`POST /api/chat`)

1. Limite do chat; mensagem sem espaços nas pontas e não vazia.
2. Sem `conversa_id`: cria a conversa com o título = a pergunta (até 60 caracteres, com "…").
   Com `conversa_id`: confere que é do usuário (404) e carrega o histórico.
3. `df = queries.tabela(db.transacoes(usuario))` e `responde(modelo, df, texto, historico)` (skill
   `app-extratos-agente`).
4. Qualquer exceção do agente → log + 502 "o assistente não conseguiu responder agora; tente de
   novo em instantes". A transação da requisição é desfeita, então nem a pergunta fica gravada.
5. Grava a pergunta e a resposta (com o gráfico). `ConversaApagada` → 404.

## Retreino (`services/retraining.py`)

- `precisa_retreinar`: correções desde a última tentativa concluída (`ok` ou `erro`) ≥ 15 e nenhum
  `rodando` há menos de 30 min. Contar só desde o último `ok` fazia cada correção seguinte a um
  erro disparar outro retreino.
- `executa_retreino`: trava de processo (`Lock.acquire(blocking=False)`) → `inicia_treino_se_livre`
  (trava do Postgres, atômica entre processos) registra `rodando` →
  lê correções → `ml.retrain.retrain(read_base(CSV base), correcoes, modelo atual)` → troca o
  `.pkl` de forma atômica → registra `ok` com as métricas. `OSError`/`ValueError` (mensagens
  próprias) → `erro` com a mensagem; outra exceção → `erro` só com o tipo, porque a mensagem
  pode trazer dados.
- Roda numa `threading.Thread(daemon=True)`, com conexão própria. Nos testes, a função que inicia
  a thread é trocada por uma que roda na hora.
- `python -m api.retrain` força um retreino agora (contra o banco do `.env`: não é um teste);
  `--historico` lista os últimos.

Código de `main.py`, `config.py`, `auth.py`, `dependencies.py`, `rate_limit.py`, `cipher.py`, dos
serviços e do `conftest.py`: [references/codigo-base.md](references/codigo-base.md).

## Testes

- `TestClient(app)`; no `conftest.py`, fixtures **autouse** para que nenhum teste use algo real:
  `DIR_PRIVADO` numa pasta vazia, `CAMINHO_MODELO` e `CAMINHO_TREINO_BASE` inexistentes, uma
  chave Fernet gerada na hora, `BancoFalso` e um `Usuario` fixo por `app.dependency_overrides`,
  retreino síncrono com o banco falso e limites zerados.
- Um arquivo por rota: importação (CSV inventado do Nubank de ponta a ponta, rejeições,
  tamanho, repetido 409, vazamento 422), extratos (lista, exclusão com herança), transações
  (filtros, correção, 404 para transação de outro usuário), painel, chat (com um modelo falso),
  conta, saúde, originais (cifrado no banco, decifrado na resposta, chave errada), retreino
  (dispara na 15ª, não dispara com outro rodando, erro registrado).
- Teste de isolamento: com `logado_como(OUTRO)`, nada do primeiro usuário aparece.
- Para o classificador, grave um `.pkl` treinado com dados inventados num `tmp_path` e aponte
  `CAMINHO_MODELO` para ele.
