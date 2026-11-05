# Módulo de ML

O parser (`python -m extrato tudo`) gera `data/saida/transacoes.csv` **sem** categoria.
Este módulo acrescenta a coluna `categoria`, sem mudar nenhuma outra coluna.

```
extrato (parser)  ->  data/saida/transacoes.csv            (8 colunas)
ml.rotular        ->  ml/dados/transacoes_rotuladas.csv    (as mesmas 8 + categoria)   treino
ml (classificador, próximo passo)  ->  CSV do parser + categoria                       aplicação
```

## Rotular o treino

```bash
python -m extrato tudo
python -m ml.rotular
```

A categoria vem de regras (receitas, financeiro, contas, transferência para pessoa) e, para compras em
estabelecimento, do mapa revisado à mão em `data/privado/estabelecimentos_revisar.csv` e
`data/privado/estabelecimentos_novos.csv` (classe em branco = aceita a sugerida). Estabelecimentos que
ainda não estão no mapa entram no fim de `estabelecimentos_novos.csv` a cada rotulagem.

## Classes

`mercado`, `alimentacao_fora`, `transporte`, `compras`, `contas_servicos`, `transferencia_pessoa`,
`receitas`, `financeiro` (ver `ml/classes.py`).

## Dados

`ml/dados/` fica fora do git: é derivado dos extratos reais.
