# Projeto TCS — Extratos bancários: extração e classificação

Lê extratos bancários reais (CSV e PDF, conta corrente e cartão de crédito), gera um CSV
padronizado e anônimo e classifica cada transação numa categoria de gasto.

## Estrutura

```
extracao/      módulo de extração (parser): extratos -> CSV padronizado e anônimo
ml/            módulo de ML: CSV do parser -> categoria de cada transação
api/           API HTTP (FastAPI): expõe a extração e a categoria para o frontend
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
navegador --(upload)--> api (POST /api/extratos) --> extração + categoria --> tabela na página
```

O arquivo enviado pela página é processado numa pasta temporária e apagado em seguida: nada fica
gravado no servidor.

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

Abra http://localhost:5173 e envie um extrato. O frontend precisa de **Node.js 22** (ou 20.19+).

A API lê (sem gravar) os mapas de `data/privado/` para anonimizar e categorizar igual à linha de
comando. Sem essa pasta, a categoria vem só das regras fixas.

## Testes

```bash
pytest
```

Roda os testes de `extracao/tests`, `ml/tests` e `api/tests`. As fixtures de teste são sempre
inventadas: nunca copie conteúdo de extrato real para os testes.

## Dados e privacidade

- Extratos reais e tudo o que é derivado deles ficam fora do git: `data/` e `ml/dados/`.
  **Nunca faça commit de extratos.**
- Notebooks gravam a saída das células: limpe as saídas (**Clear All Outputs**) antes de fazer
  commit de um `.ipynb`.
