---
name: app-extratos-ml
description: Como construir a camada de ML que categoriza transações bancárias (mercado, alimentação fora, transporte, compras, contas e serviços, transferência para pessoa, receitas, financeiro). Cobre a rotulagem do treino com regras + mapa de estabelecimentos, a comparação de modelos com validação por usuário (GroupKFold), o modelo escolhido (TF-IDF de caracteres na contraparte + one-hot + SVM linear num Pipeline do scikit-learn salvo em .pkl), o uso na API e o retreino automático com as correções dos usuários. Use sempre que for classificar, rotular, treinar, avaliar ou retreinar o modelo de categorias de gastos, ou quando a categoria prevista estiver errada.
---

# Camada de ML (`ml/`)

Entrada: o CSV do parser (8 colunas, ver `app-extratos` › `references/contratos.md`). Saída: a
categoria de cada transação. O pré-processamento fica **dentro** do `.pkl`: o modelo recebe as
colunas do parser como estão e devolve a categoria, sem código extra na API.

```
python -m statement tudo  ->  data/saida/transacoes.csv            (8 colunas)
python -m ml.label        ->  ml/dados/transacoes_rotuladas.csv    (8 + categoria)   treino
python -m ml.train        ->  ml/modelos/svm_tfidf.pkl             (modelo final)
API                       ->  entrada = receitas (regra); saída = modelo.predict
```

`ml/dados/` e `ml/modelos/` ficam fora do git: o CSV vem de extratos reais e o vocabulário do
TF-IDF guarda pedaços de nomes reais de lojas.

## Arquivos

| Arquivo | Para quê |
|---|---|
| `classes.py` | as 8 classes (`Category`) e as regras que não dependem do nome (`by_rule`) |
| `label.py` | CSV do parser + `categoria` (regras + mapa de estabelecimentos) |
| `train.py` | `build_model()` e o treino final com todo o CSV rotulado |
| `retrain.py` | treino com as correções dos usuários (sem banco: recebe tudo pronto) |
| `exploration.ipynb` | comparação de modelos e representações; justifica o campeão |
| `champion_model.ipynb` | o campeão isolado: métricas, por usuário, pesos, erros, `.pkl` |
| `tests/` | dados inventados |

## 1. Classes e regras

As 8 classes foram combinadas com o usuário. Mudar a lista exige mudar o `CHECK` do banco, o
prompt do agente e o frontend.

`by_rule(meio, tipo, historico, contraparte)` decide o que não depende do nome do estabelecimento:

- investimento, rendimento, tarifa, juros/IOF, saque, estorno, pagamento de fatura,
  transferência interna → `financeiro`;
- salário → `receitas`;
- `outros`: entrada → `receitas`; saída com "RECARGA" → `contas_servicos`; senão `financeiro`;
- outras entradas → `receitas` (crédito do cartão movido para a conta → `financeiro`);
- boleto pago → `contas_servicos`;
- contraparte `PESSOA_FISICA`, ou PIX/TED sem contraparte → `transferencia_pessoa`;
- o resto (compra em estabelecimento, PIX para empresa) → `None`: depende do nome.

Código em [references/codigo-ml.md](references/codigo-ml.md).

## 2. Rotulagem do treino (`python -m ml.label`)

Entrada: exatamente o CSV do parser (cabeçalho conferido). Saída: as mesmas colunas, na mesma
ordem e com os mesmos valores, mais `categoria` no fim.

1. `by_rule` primeiro.
2. Senão, o **mapa de estabelecimentos**, mantido à mão pelo usuário em `data/privado/` (tem nomes
   reais, fora do git):
   - `estabelecimentos_revisar.csv` é o primeiro mapa (prioridade); `estabelecimentos_novos.csv`
     cresce a cada rotulagem com o que ainda não está mapeado;
   - colunas: `contraparte, linhas, classe_sugerida, regra_achou_classe, nome_canonico_sugerido,
     parece_pessoa, classe, nome_canonico, e_pessoa`;
   - `classe` em branco = aceita a `classe_sugerida` (decisão do usuário: ele só preenche quando
     discorda);
   - a chave é o **nome-base** do estabelecimento (`statement.merchants.base_name`), o mesmo que o
     parser grava;
   - `e_pessoa = sim` faz o parser trocar aquele nome por `PESSOA_FISICA`;
   - classe inválida é erro, com o arquivo e a linha, para corrigir na planilha.
3. Estabelecimentos novos entram no fim de `estabelecimentos_novos.csv` com uma classe sugerida
   por palavras-chave (padrão `compras`). Nunca apague nem altere linhas já existentes: o usuário
   pode estar preenchendo.
4. Linha sem categoria → `""` no CSV rotulado. O treino recusa linhas sem categoria: rotule tudo
   antes de treinar.

Fluxo com o usuário: rotular → ele revisa as linhas novas do mapa → rotular de novo → treinar.

## 3. Escolha do modelo

Métricas: **acurácia** e **F1 macro** (média do F1 por classe, que dá o mesmo peso às classes
pequenas). Duas validações:

- **por usuário** (`GroupKFold(5)` com `groups=id_usuario`): todas as transações de uma pessoa
  ficam no treino ou no teste. Mede o caso real (usuário novo na aplicação) e **é a que decide**;
- **aleatória** (`StratifiedKFold(5)`): otimista, porque as mesmas lojas aparecem nos dois lados.

Todo o pré-processamento fica dentro de um `Pipeline`, ajustado só no treino de cada fold.

Resultado na referência (8 usuários, ~9.300 transações):

| Etapa | Achado |
|---|---|
| 9 classificadores com one-hot | SVM linear o melhor (F1 macro por usuário 0,72); lineares generalizam melhor; Gaussian NB o pior |
| TF-IDF de caracteres na contraparte | **a maior melhoria**: SVM 0,72 → 0,90 de F1 por usuário, porque lojas nunca vistas são reconhecidas por pedaços do nome (`SUPERMERC`, `LANCH`, `POSTO`) |
| com x sem data | a data não ajuda (diferença ≤ 0,002): sai do modelo |
| ajuste de `C` e `class_weight` | diferenças menores que a variação entre usuários: fica o padrão (`C=1`) |

Campeão: **F1 macro 0,903 e acurácia 0,928 por usuário** (0,987 na aleatória).

Limitações conhecidas, que devem ser contadas ao usuário:
- `compras` funciona como "classe de dúvida": quando não reconhece a loja, o modelo tende a ela;
- usuários com um banco que só eles têm vão pior (o histórico daquele banco é novo para o
  modelo);
- com poucos usuários, os números variam bastante conforme quem fica no teste.

## 4. O modelo (`ml/train.py`)

```python
TARGET = "categoria"
CATEGORICAL = ["historico", "meio", "tipo", "banco"]


def build_model() -> Pipeline:
    valor = Pipeline([
        ("abs", FunctionTransformer(np.abs, feature_names_out="one-to-one")),    # o sinal já está em "tipo"
        ("log", FunctionTransformer(np.log1p, feature_names_out="one-to-one")),  # reduz a cauda longa
        ("minmax", MinMaxScaler()),
    ])
    prep = ColumnTransformer([
        ("contraparte", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=3, sublinear_tf=True),
         "contraparte"),
        ("cat", OneHotEncoder(min_frequency=5, handle_unknown="infrequent_if_exist"), CATEGORICAL),
        ("valor", valor, ["valor"]),
    ])  # id_usuario e data são ignorados (remainder="drop")
    return Pipeline([("prep", prep), ("clf", LinearSVC())])
```

- `train_model(csv)` lê com `keep_default_na=False` (contraparte vazia continua `""`, não `NaN`),
  recusa linhas sem categoria e treina com tudo.
- `python -m ml.train [--entrada ...] [--saida ...]` grava com `joblib.dump` e imprime as classes.
- O `.pkl` só carrega com a **mesma versão do scikit-learn**: fixe a versão no
  `requirements.txt`.
- Uso: `modelo = joblib.load(caminho); df["categoria_prevista"] = modelo.predict(df)`, onde `df`
  tem as 8 colunas do parser.

## 5. Na API

- Toda **entrada** é `receitas`, com origem `regra`. Toda **saída** vai para o modelo, com origem
  `modelo`. As regras e o mapa **não** entram na inferência: o modelo aprendeu o que eles faziam.
  Medido nas saídas: ~99% de acerto em estabelecimento já visto, 100% em PIX para pessoa, tarifa e
  fatura, ~81% em estabelecimento nunca visto.
- O modelo é carregado uma vez e guardado com a data de modificação do arquivo: se o `.pkl` mudar
  (retreino), a próxima importação carrega o novo sozinha.
- Sem `.pkl` (ou se ele não carregar), as saídas ficam sem categoria e a importação continua.
- Para a predição, monte um `DataFrame` com as 8 colunas (`id_usuario` vazio, `data` ISO, `valor`
  como `float`).

## 6. Retreino com as correções dos usuários

Na aba Extrato o usuário corrige a categoria (origem `usuario`). A cada **15 correções novas**
(de todos os usuários) desde a última tentativa de retreino (com sucesso ou erro: assim uma falha
não dispara um retreino a cada clique), a API treina de novo em segundo
plano:

- treino = CSV rotulado base + as correções (`ml/retrain.py`);
- cada correção pesa **5** (`sample_weight`): uma só já muda o modelo;
- a correção **substitui o rótulo** do mesmo estabelecimento (nome-base) no CSV base, menos
  `PESSOA_FISICA` e contraparte vazia, porque corrigir um PIX para um amigo não muda todos os PIX
  para pessoas;
- correções que discordam no mesmo estabelecimento: vale a mais recente;
- só campos anonimizados entram no treino, nunca o texto original;
- o `.pkl` é trocado de forma atômica (grava `.novo.pkl`, copia o atual para `.anterior.pkl`,
  `os.replace`);
- cada retreino é registrado (tabela `treinos_modelo`): acerto nas correções antes e depois e
  acerto no CSV base. Na referência, o modelo novo entra sempre (decisão do usuário); uma
  alternativa é só trocar se o acerto no CSV base não cair.

Código em [references/codigo-ml.md](references/codigo-ml.md); a orquestração (thread, trava,
registro) está na skill `app-extratos-api`.

**Correções numa tabela própria** (decisão do usuário). Se as correções vivessem só na tabela
de transações, excluir o extrato as apagaria, e o próximo retreino "esqueceria" o que elas
ensinaram (as lojas voltariam ao rótulo antigo do CSV base). Por isso elas ficam em
`correcoes`, só com campos anonimizados: sobrevivem à exclusão do extrato e são apagadas em
cascata com a conta (ver `app-extratos-banco`).

## 7. Notebooks

- `exploration.ipynb`: dados → atributos → validação → comparação de modelos → representação →
  ajuste → conclusão, com uma "Leitura" em texto depois de cada resultado.
- `champion_model.ipynb`: usa `from ml.train import build_model`, o mesmo do `.pkl`. Mostra
  métricas (`cross_val_predict`), desempenho por usuário, os pesos de maior valor por classe, os
  pares de erro mais frequentes e o treino final.
- As saídas das células têm dados derivados dos extratos (nomes de lojas nos pesos). Antes de
  fazer commit, **limpe as saídas** (Clear All Outputs) e confira com um script que o `.ipynb` não
  tem `outputs`.

## 8. Testes (dados inventados)

- `by_rule`: cada regra (fatura → financeiro, boleto → contas, PIX para `PESSOA_FISICA` →
  transferência, compra em loja → `None`).
- `label_csv`: mantém as 8 colunas e os valores; mapa com prioridade (revisar > novos; mais linhas
  ganha); classe em branco aceita a sugerida; classe inválida dá erro; novos estabelecimentos são
  acrescentados sem tocar nos existentes.
- `train`: treina, salva, carrega e prevê com o CSV do parser; banco nunca visto não quebra
  (`handle_unknown`); `id_usuario` e `data` não mudam a previsão.
- `retrain`: substitui o rótulo do mesmo estabelecimento; não toca em `PESSOA_FISICA`; a correção
  mais recente vence; pesos 5; métricas antes e depois.

Dados inventados com classes bem separadas (padarias → mercado, lanchonetes → alimentação fora)
e cada linha repetida algumas vezes, porque o TF-IDF usa `min_df=3` e o one-hot usa
`min_frequency=5`.
