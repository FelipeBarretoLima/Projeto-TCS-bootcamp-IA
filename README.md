# Projeto TCS — Extratos bancários: extração e classificação

Lê extratos bancários reais (CSV e PDF, conta corrente e cartão de crédito), gera um CSV
padronizado e anônimo e classifica cada transação numa categoria de gasto.

## Estrutura

```
extracao/      módulo de extração (parser): extratos -> CSV padronizado e anônimo
ml/            módulo de ML: CSV do parser -> categoria de cada transação
data/          extratos reais e saídas (fora do git)
```

Cada módulo tem o seu README: [extracao/README.md](extracao/README.md) e [ml/README.md](ml/README.md).

Fluxo:

```
data/raw/  --(python -m extrato tudo)-->  data/saida/transacoes.csv  --(ml)-->  CSV + categoria
```

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
`scikit-learn`, `matplotlib` e `ipykernel`. Com o venv ativo, o terminal mostra `(.venv)` no início
da linha. Para sair do venv: `deactivate`.

## Testes

```bash
pytest
```

Roda os testes dos dois módulos (`extracao/tests` e `ml/tests`). As fixtures de teste são sempre
inventadas: nunca copie conteúdo de extrato real para os testes.

## Dados e privacidade

- Extratos reais e tudo o que é derivado deles ficam fora do git: `data/` e `ml/dados/`.
  **Nunca faça commit de extratos.**
- Notebooks gravam a saída das células: limpe as saídas (**Clear All Outputs**) antes de fazer
  commit de um `.ipynb`.
