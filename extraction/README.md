# Módulo de extração

Lê extratos bancários (CSV e PDF) e gera um CSV padronizado e anônimo, sem categoria:

```csv
id_usuario,data,historico,contraparte,valor,tipo,meio,banco
```

Cada formato de extrato tem um parser próprio e determinístico (`src/statement/parsers/`), e cada
arquivo é conferido contra os totais que o próprio documento declara antes de ser aceito.

## Uso

Com o venv ativo, na raiz do projeto:

```bash
python -m statement extrair --entrada data/raw/<pasta> --usuario u07 --saida data/saida/u07.csv
```

Para processar todas as pastas de uma vez e gerar o CSV geral:

```bash
python -m statement tudo
```

Cada subpasta de `data/raw/` é um usuário, com o número da pasta como pseudônimo (`data/raw/7` → `u07`).
Grava `data/saida/uNN.csv` para cada usuário e `data/saida/transacoes.csv` com tudo junto. O nome
do titular de qualquer pasta é removido das outras e conferido de novo no CSV geral.

Cada execução gera também `data/saida/uNN.relatorio.csv` (só contagens por arquivo).
Linhas ambíguas vão para `data/privado/revisar.csv` e históricos fora do mapa de um parser
para `data/privado/historicos_desconhecidos.csv`. Os dois ficam fora do git.

Código de saída: `0` tudo aceito, `1` algum arquivo rejeitado, `2` gravação bloqueada por
possível vazamento de dado pessoal, `3` argumento inválido.

## Formatos suportados

| Parser | Banco / produto |
|---|---|
| `bradesco_conta_pdf` | Bradesco, conta corrente (Internet Banking) |
| `bradesco_cartao_pdf` | Bradesco, fatura de cartão |
| `inter_conta_pdf` | Inter, conta |
| `nubank_conta_csv` | Nubank, conta (CSV exportado pelo app) |
| `nubank_conta_pdf` | Nubank, conta (PDF) |
| `nubank_fatura_pdf` | Nubank, fatura de cartão |
| `santander_cartao_pdf` | Santander, fatura de cartão |
| `sicoob_conta_pdf` | Sicoob, conta corrente |

## Estrutura

```
src/statement/
  parsers/          um parser por formato + registry (detecção do formato)
  reconciliation.py conferência contra os totais do documento
  anonymization.py  remoção de dado pessoal e regra de contraparte
  merchants.py      nome-base do estabelecimento e pessoa física na maquininha
  validation.py     bloqueia a gravação se achar dado pessoal no CSV
  pipeline.py, cli.py
  dados/            listas públicas (municípios do IBGE, primeiros nomes)
tests/              testes com dados inventados
```
