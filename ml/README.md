# Módulo de ML

Classifica cada transação do CSV do parser em uma de 8 categorias. O parser (`python -m extrato tudo`)
gera `data/saida/transacoes.csv` **sem** categoria; este módulo rotula o treino, compara modelos e
gera o modelo final.

```
extrato (parser)  ->  data/saida/transacoes.csv            (8 colunas)
ml.rotular        ->  ml/dados/transacoes_rotuladas.csv    (as mesmas 8 + categoria)   treino
ml.treinar        ->  ml/modelos/svm_tfidf.pkl             (modelo final)
.pkl              ->  CSV do parser + categoria prevista                               aplicação
```

## Arquivos

| Arquivo | Para quê |
|---|---|
| `exploracao.ipynb` | **Escolha do modelo**: compara 9 classificadores, one-hot × TF-IDF na contraparte, com e sem data, e o ajuste do SVM. Justifica o campeão. |
| `modelo_campeao.ipynb` | **O modelo escolhido isolado**: pipeline, métricas, heatmaps, desempenho por usuário, o que aprendeu, onde erra e o `.pkl`. |
| `rede_neural.ipynb` | Experimento com rede neural (PyTorch, GPU). |
| `treinar.py` | Monta o modelo campeão (`monta_modelo()`), treina com todo o CSV rotulado e salva o `.pkl`. |
| `rotular.py` | Gera o CSV de treino: CSV do parser + `categoria` (regras + mapa de estabelecimentos). |
| `classes.py` | As 8 classes e as regras determinísticas (financeiro, receitas, contas, transferência). |
| `tests/` | Testes com dados inventados (`pytest` na raiz). |
| `dados/`, `modelos/` | CSV rotulado e `.pkl` — **fora do git** (derivados dos extratos reais). |

## Modelo escolhido

**SVM linear + TF-IDF de caracteres na `contraparte`**, one-hot em `historico`/`meio`/`tipo`/`banco`
e `log + min-max` no valor, sem data. Os números e a justificativa estão em `exploracao.ipynb`.

## Comandos

```bash
python -m extrato tudo     # extratos -> CSV do parser
python -m ml.rotular       # CSV do parser -> CSV rotulado (treino)
python -m ml.treinar       # CSV rotulado -> ml/modelos/svm_tfidf.pkl
```

A categoria do treino vem de regras (receitas, financeiro, contas, transferência para pessoa) e, para
compras em estabelecimento, do mapa revisado à mão em `data/privado/estabelecimentos_revisar.csv` e
`data/privado/estabelecimentos_novos.csv` (classe em branco = aceita a sugerida). Estabelecimentos que
ainda não estão no mapa entram no fim de `estabelecimentos_novos.csv` a cada rotulagem.

## Retreino com as correções dos usuários

Na aba Extrato o usuário corrige a categoria de uma transação (origem `usuario`). A cada **15
correções novas** (de todos os usuários) desde o último retreino, a API treina o modelo de novo em
segundo plano e troca o `.pkl` (o anterior fica em `svm_tfidf.anterior.pkl`):

- treino = CSV rotulado base (`ml/dados/transacoes_rotuladas.csv`) + as correções (`ml/retreinar.py`);
- cada correção pesa 5 e substitui o rótulo automático do mesmo estabelecimento no CSV base (menos
  `PESSOA_FISICA` e contraparte vazia); correções que discordam: vale a mais recente;
- só campos anonimizados entram no treino (nunca o texto original cifrado);
- o modelo novo entra sempre; cada retreino fica registrado na tabela `treinos_modelo` (acerto nas
  correções antes/depois e no CSV base).

```bash
python -m api.retreinar              # força um retreino agora
python -m api.retreinar --historico  # últimos retreinos e seus acertos
```

O CSV base precisa estar na máquina que roda a API (fica fora do git); sem ele, o retreino é
registrado com erro e a correção do usuário continua valendo normalmente.

## Usar o modelo

O pré-processamento está dentro do `.pkl`: ele recebe o CSV do parser como está e devolve a categoria.

```python
import joblib, pandas as pd
modelo = joblib.load("ml/modelos/svm_tfidf.pkl")
extrato = pd.read_csv("data/teste_saida/u99.csv", keep_default_na=False)
extrato["categoria_prevista"] = modelo.predict(extrato)
```

Extratos de teste ficam **fora de `data/raw/`** (ex.: `data/teste/`), para não entrarem no treino.

## Classes

`mercado`, `alimentacao_fora`, `transporte`, `compras`, `contas_servicos`, `transferencia_pessoa`,
`receitas`, `financeiro` (ver `classes.py`).

## Notebooks e privacidade

As saídas das células podem conter dados derivados dos extratos (o `modelo_campeao.ipynb` mostra pedaços
de nomes de lojas). Antes de fazer commit: **Clear All Outputs**.
