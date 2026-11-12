# Projeto TCS — Extratos bancários: extração e classificação

Lê extratos bancários reais (CSV e PDF, conta corrente e cartão de crédito), gera um CSV
padronizado e anônimo e classifica cada transação numa categoria de gasto.

## Estrutura

```
extracao/      módulo de extração (parser): extratos -> CSV padronizado e anônimo
ml/            módulo de ML: CSV do parser -> categoria de cada transação
api/           API HTTP (FastAPI): importação, dashboard, chat e login
banco/         banco de dados (PostgreSQL no Supabase): tabelas e acesso
agente/        Assistente TAS: consultas fixas (pandas) + Gemini (LangChain)
frontend/      página web (React + TypeScript + Vite)
data/          extratos reais e saídas (fora do git)
```

Cada módulo tem o seu README: [extracao/README.md](extracao/README.md), [ml/README.md](ml/README.md)
e [frontend/README.md](frontend/README.md).

Fluxo pela linha de comando:

```
data/raw/  --(python -m extrato tudo)-->  data/saida/transacoes.csv  --(ml)-->  CSV + categoria
```

Fluxo pela página:

```
login (Supabase Auth) --> upload --> api: extração + categoria --> transações salvas no banco
dashboard / chat --> api: consultas fixas sobre as transações do usuário --> números + gráfico
```

O arquivo enviado pela página é processado numa pasta temporária e apagado em seguida: só as
transações extraídas (já anonimizadas) ficam salvas, na conta de quem enviou. Uma compra que
aparece em dois extratos com períodos sobrepostos entra uma vez só (`banco/deduplicacao.py`).

O assistente nunca faz contas nem vê a lista de transações: o Gemini escolhe uma das consultas de
`agente/consultas.py`, que calcula com pandas e devolve só os totais e os dados do gráfico.

## Arquivo `.env` (raiz, fora do git)

| Variável | Onde pegar |
|---|---|
| `DATABASE_URL` | Supabase > **Connect** > **Session pooler** > URI (senha no lugar de `[YOUR-PASSWORD]`, sem colchetes) |
| `SUPABASE_PUBLISHABLE_KEY` | Supabase > **Project Settings** > **API Keys** > Publishable key (`sb_publishable_...`) |
| `GEMINI_API_KEY` | aistudio.google.com > **Get API key** |
| `GEMINI_MODEL` | opcional; padrão `gemini-3.5-flash-lite` (o mais rápido e estável nos testes) |
| `GEMINI_MODELOS_RESERVA` | opcional; padrão `gemini-3.6-flash,gemini-3.1-flash-lite`. Se o principal falhar (ex.: 503 "high demand") ou demorar, a pergunta vai para estes, em ordem |
| `GEMINI_TIMEOUT` | opcional; padrão `10` (segundos por modelo antes de passar para o próximo; uma chamada normal leva 1-3 s) |
| `CHAVE_ORIGINAIS` | cifra o texto original das transações (sem anonimizar), que só o dono vê. Gere com `python -m api.cifra --nova-chave` **uma vez** e passe a **mesma** chave para toda a equipe (por um canal privado, nunca no git). Sem ela, a tela mostra o texto anonimizado. Perder a chave = os originais já gravados não abrem mais. |
| `CORS_ORIGENS` | opcional; só se a página for publicada num domínio diferente do da API (vários: separe por vírgula) |

`SUPABASE_URL` é deduzido do `DATABASE_URL`. Nunca faça commit do `.env` nem cole o conteúdo dele
em chats.

## Pré-requisito

**Python 3.12.** Confira com `python --version` (Windows) ou `python3 --version` (macOS/Linux).

> Se você tiver mais de uma versão do Python instalada, troque `python` por
> `py -3.12` no Windows ou por `python3.12` no macOS/Linux ao criar o venv.

## Configurar o ambiente

Rode os comandos na pasta raiz do projeto.

### Windows (PowerShell)

```powershell
# 1. Criar o ambiente virtual
python -m venv .venv

# 2. Ativar
.\.venv\Scripts\Activate.ps1

# 3. Instalar as dependências (dos dois módulos)
pip install -r requirements.txt

# 4. Conferir
pip list
```

Se o passo 2 der erro de "execução de scripts desabilitada", rode uma vez
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` e tente de novo.

No passo 4, a lista deve mostrar `pdfplumber`, `pandas`, `pydantic`, `python-dotenv`, `pytest`,
`scikit-learn`, `matplotlib`, `ipykernel`, `fastapi` e `uvicorn`. Com o venv ativo, o terminal mostra
`(.venv)` no início da linha. Para sair do venv: `deactivate`.

## Rodar a página

São dois servidores, cada um num terminal (com o venv ativo no primeiro):

```bash
# Terminal 1, na raiz: a API em http://localhost:8000 (documentação em /docs)
uvicorn api.main:app --reload

# Terminal 2: o frontend em http://localhost:5173
cd frontend
npm install      # só na primeira vez
npm run dev
```

Abra http://localhost:5173, crie uma conta, importe um extrato e converse com o assistente no
dashboard. O frontend precisa de **Node.js 22** (ou 20.19+). Antes da primeira vez, preencha o
`.env` (acima) e crie as tabelas (abaixo). Depois de mudar o `.env`, reinicie a API.

A API lê (sem gravar) os mapas de `data/privado/` só para anonimizar. A categoria vem de duas
formas: toda **entrada** (dinheiro recebido) é `receitas`, por regra; toda **saída** é classificada
pelo modelo `ml/modelos/svm_tfidf.pkl` (gerado por `python -m ml.treinar`). Sem o `.pkl`, as saídas
ficam sem categoria. As regras fixas e o mapa de estabelecimentos só geram os rótulos do treino
(`python -m ml.rotular`); o modelo aprendeu o que eles faziam.

Na aba Extrato, o usuário pode corrigir a categoria de uma transação (vale para o dashboard e o
assistente; fica gravada com origem `usuario`). Para evitar abuso, cada usuário pode fazer até 10
perguntas por minuto ao assistente e importar até 20 extratos a cada 10 minutos (`api/limite.py`).

### Publicar (um único servidor)

```bash
cd frontend && npm run build && cd ..   # gera frontend/dist
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

Com `frontend/dist` presente, a própria API serve a página em http://localhost:8000. No Supabase
(**Authentication > URL Configuration**), coloque o endereço publicado como **Site URL** e em
**Redirect URLs** (o link de recuperar senha volta para `/redefinir-senha`). Depois de publicar uma
versão nova, rode o `npm run build` de novo; para voltar a desenvolver só com o Vite, apague `frontend/dist`.

## Banco de dados (Supabase)

PostgreSQL no Supabase. Login e senha ficam no Supabase Auth; as tabelas do projeto (`usuarios`,
`extratos`, `transacoes`, `conversas`, `mensagens`) estão em `banco/migracoes/`.

1. Crie um arquivo `.env` na raiz (fora do git) com `DATABASE_URL=` + a connection string do
   Supabase (botão **Connect** > **Session pooler** > URI, com a senha no lugar de `[YOUR-PASSWORD]`,
   sem os colchetes).
2. Rode `python -m banco.migrar` para criar ou atualizar as tabelas (`--status` só mostra o que falta).

Para mudar o banco, crie uma migração nova (`0002_...sql`); nunca edite uma já aplicada.

## Testes

```bash
pytest
```

Roda os testes de `extracao/tests`, `ml/tests`, `api/tests`, `banco/tests` e `agente/tests`, sem
internet: o banco, o login e o Gemini são trocados por versões falsas. Para testar também contra o
banco de verdade (numa transação desfeita no fim, nada fica gravado): `TESTE_BANCO=1 pytest`.
As fixtures de teste são sempre inventadas: nunca copie conteúdo de extrato real para os testes.

## Dados e privacidade

- Extratos reais e tudo o que é derivado deles ficam fora do git: `data/` e `ml/dados/`.
  **Nunca faça commit de extratos.**
- Notebooks gravam a saída das células: limpe as saídas (**Clear All Outputs**) antes de fazer
  commit de um `.ipynb`.
