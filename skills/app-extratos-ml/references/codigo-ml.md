# Código da camada de ML

Do projeto de referência (`ml/`). Importa o contrato do pacote `statement` (camada de extração).

## Sumário

1. `classes.py`
2. `label.py`: mapa de estabelecimentos e rotulagem
3. Avaliação (notebook)
4. `retrain.py`
5. Teste do treino

## 1. `classes.py`

```python
from enum import StrEnum

from statement.models import INDIVIDUAL_PERSON, PaymentMethod, TransactionType


class Category(StrEnum):
    GROCERIES = "mercado"
    EATING_OUT = "alimentacao_fora"
    TRANSPORT = "transporte"
    SHOPPING = "compras"
    BILLS_SERVICES = "contas_servicos"
    PERSON_TRANSFER = "transferencia_pessoa"
    INCOME = "receitas"
    FINANCIAL = "financeiro"


_FINANCIAL = {PaymentMethod.INVESTMENT, PaymentMethod.YIELD, PaymentMethod.FEE, PaymentMethod.INTEREST_IOF,
              PaymentMethod.WITHDRAWAL, PaymentMethod.REFUND, PaymentMethod.INVOICE_PAYMENT,
              PaymentMethod.INTERNAL_TRANSFER}


def by_rule(meio: PaymentMethod, tipo: TransactionType, historico: str, contraparte: str) -> Category | None:
    """Categoria que não depende do nome do estabelecimento (None = depende do nome)."""
    if meio in _FINANCIAL:
        return Category.FINANCIAL
    if meio is PaymentMethod.SALARY:
        return Category.INCOME
    if meio is PaymentMethod.OTHER:
        if tipo is TransactionType.INCOME:
            return Category.INCOME
        return Category.BILLS_SERVICES if "RECARGA" in historico else Category.FINANCIAL
    if tipo is TransactionType.INCOME:
        # crédito do cartão movido para a conta (Nubank) é movimento financeiro, não receita
        return Category.FINANCIAL if meio is PaymentMethod.CREDIT_CARD else Category.INCOME
    if meio is PaymentMethod.BANK_SLIP:
        return Category.BILLS_SERVICES
    if contraparte == INDIVIDUAL_PERSON:
        return Category.PERSON_TRANSFER
    if meio in (PaymentMethod.PIX, PaymentMethod.TED_DOC) and not contraparte:
        return Category.PERSON_TRANSFER
    return None
```

## 2. `label.py`

```python
REVIEWED_FILE = "estabelecimentos_revisar.csv"
NEW_FILE = "estabelecimentos_novos.csv"
MAP_COLUMNS = ["contraparte", "linhas", "classe_sugerida", "regra_achou_classe", "nome_canonico_sugerido",
               "parece_pessoa", "classe", "nome_canonico", "e_pessoa"]
LABELED_COLUMNS = (*COLUMNS, "categoria")


def _read(path):
    if not path.exists():
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:  # utf-8-sig: planilha salva pelo Excel
        return list(csv.DictReader(f))


def load_map(private_dir) -> dict[str, Category]:
    """nome-base -> classe. Mesmo nome-base com classes diferentes: ganha o arquivo revisado e,
    no mesmo arquivo, a linha com mais ocorrências."""
    name_map, weight = {}, {}
    for priority, map_file in enumerate((REVIEWED_FILE, NEW_FILE)):
        for n, r in enumerate(_read(private_dir / map_file), start=2):
            class_name = (r.get("classe") or "").strip() or r.get("classe_sugerida", "")
            if not class_name:
                continue
            if class_name not in Category.__members__.values():
                raise ValueError(f"{map_file}, linha {n}: classe inválida (use uma das 8 classes)")
            keys = {base_name(r["contraparte"])}
            if (r.get("nome_canonico") or "").strip():
                keys.add(base_name(r["nome_canonico"]))
            p = (-priority, int(r.get("linhas") or 0))
            for k in keys:
                if k and (k not in weight or p > weight[k]):
                    name_map[k], weight[k] = Category(class_name), p
    return name_map


def category_for(row: dict[str, str], name_map) -> Category | None:
    rule = by_rule(PaymentMethod(row["meio"]), TransactionType(row["tipo"]), row["historico"], row["contraparte"])
    # o mapa é indexado pelo nome-base (PIX para empresa chega sem a padronização de cartão)
    return rule if rule is not None else name_map.get(base_name(row["contraparte"]))


# sugestão para o que ainda não está no mapa (a primeira regra que casar)
_CLASS_RULES = [
    (Category.EATING_OUT, r"\bIFD\b|IFOOD|LANCH|RESTAUR|PIZZ|BURG|FOODS?\b|\bBAR\b|BEER|CAFE|SORVET|CHURRAS|"
                          r"ACAI|PASTEL|SUSHI|OUTBACK|MC ?DONALD|\bBK\b|SUBWAY|ESPETO|CHOPP|BISTRO|COZINHA"),
    (Category.GROCERIES, r"SUPER|MERCAD|SACOLAO|ASSAI|ATACAD|HORTI|PADARIA|PANIF|ACOUGUE|EMPORIO|"
                         r"BEBID|CONVENIENC|FRUT|QUITANDA|ARMAZEM"),
    (Category.TRANSPORT, r"UBER|\b99\b|POSTO|COMBUST|PEDAGIO|SEM PARAR|ESTACION|AUTO ?PECAS|PNEU|MECANIC"),
    (Category.BILLS_SERVICES, r"TOTALPASS|NETFLIX|SPOTIFY|BYTEDANCE|GOOGLE|APPLE|PRIME|DISNEY|YOUTUBE|DEEZER|"
                              r"OPENAI|MICROSOFT|FARMA|DROGA|RAIA|PACHECO|CLINIC|ODONTO|HOSPITAL|LABORAT|"
                              r"CLARO|VIVO|\bTIM\b|\bOI\b|ENERGIA|SANEAMENTO|ACADEMIA|SMART ?FIT"),
    (Category.SHOPPING, r"SHOPEE|SHPP|MERCADO ?LIVRE|AMAZON|MAGAZINE|MAGALU|AMERICANAS|ALIEXPRESS|SHEIN|RENNER|"
                        r"RIACHUELO|\bC ?& ?A\b|LOJA|MODAS?|CALCAD|ELETRO|PAPELAR"),
]


def suggest_class(contraparte: str) -> Category | None:
    c = strip_accents(contraparte).upper()
    return next((k for k, rx in _CLASS_RULES if re.search(rx, c)), None)


def update_new(private_dir, uncategorized) -> int:
    """Acrescenta ao fim de estabelecimentos_novos.csv o que não está em nenhum mapa.
    Nunca apaga nem altera linhas existentes."""
    path = private_dir / NEW_FILE
    already = {base_name(r["contraparte"]) for f in (REVIEWED_FILE, NEW_FILE) for r in _read(private_dir / f)}
    counts = Counter(c for c in uncategorized if c and c != INDIVIDUAL_PERSON and base_name(c) not in already)
    if not counts:
        return 0
    rows = []
    for c, n in counts.most_common():
        sugg = suggest_class(c)
        rows.append({"contraparte": c, "linhas": str(n), "classe_sugerida": sugg.value if sugg else "compras",
                     "regra_achou_classe": "sim" if sugg else "não (padrão: compras)",
                     "nome_canonico_sugerido": c, "parece_pessoa": "sim" if looks_like_person(c) else "",
                     "classe": "", "nome_canonico": "", "e_pessoa": ""})
    existed = path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=MAP_COLUMNS, lineterminator="\n")
        if not existed:
            w.writeheader()
        w.writerows(rows)
    return len(rows)


def label_csv(source, output, private_dir):
    with open(source, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if tuple(reader.fieldnames or ()) != COLUMNS:
            raise ValueError("a entrada não está no contrato do parser (cabeçalho diferente)")
        rows = list(reader)
    name_map = load_map(private_dir)
    missing, by_category = [], Counter()
    temp = output.with_name(output.name + ".tmp")
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(temp, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(LABELED_COLUMNS)
        for l in rows:
            c = category_for(l, name_map)
            if c is None:
                missing.append(l["contraparte"])
            by_category[c.value if c else "(sem categoria)"] += 1
            w.writerow([*(l[k] for k in COLUMNS), c.value if c else ""])
    temp.replace(output)
    novos = update_new(private_dir, missing)
    return len(rows), by_category, novos
```

A CLI imprime a distribuição por categoria (contagem e %) e quantos estabelecimentos novos
entraram no mapa.

## 3. Avaliação (notebook)

```python
import pandas as pd
from sklearn.model_selection import GroupKFold, StratifiedKFold, cross_validate, cross_val_predict
from sklearn.metrics import classification_report

from ml.train import build_model

df = pd.read_csv("ml/dados/transacoes_rotuladas.csv", keep_default_na=False)
X, y, grupos = df.drop(columns=["categoria"]), df["categoria"], df["id_usuario"]
metricas = ["accuracy", "f1_macro"]

por_usuario = cross_validate(build_model(), X, y, groups=grupos, cv=GroupKFold(n_splits=5), scoring=metricas)
aleatoria = cross_validate(build_model(), X, y, scoring=metricas,
                           cv=StratifiedKFold(n_splits=5, shuffle=True, random_state=0))
print({k: v.mean().round(3) for k, v in por_usuario.items() if k.startswith("test_")})

# cada transação prevista por um modelo que não a viu (e não viu nada do usuário dela)
previsto = cross_val_predict(build_model(), X, y, groups=grupos, cv=GroupKFold(n_splits=5))
print(classification_report(y, previsto, digits=3))
```

Para comparar classificadores, troque o passo `clf` (`LogisticRegression`, `RandomForest`,
`HistGradientBoosting`, `ExtraTrees`, `DecisionTree`, `ComplementNB`, `KNN`, `GaussianNB`). Os que
não aceitam matriz esparsa (GaussianNB, HistGradientBoosting) precisam do one-hot denso
(`sparse_output=False`). Compare também one-hot × TF-IDF na contraparte e com × sem atributos de
data (dia da semana, dia do mês, mês).

Pesos aprendidos, para o notebook do campeão:

```python
modelo = build_model().fit(X, y)
nomes = modelo.named_steps["prep"].get_feature_names_out()   # "contraparte__xyz", "cat__meio_pix"...
pesos = modelo.named_steps["clf"].coef_                       # uma linha por classe (um-contra-todos)
```

## 4. `retrain.py`

```python
CORRECTION_WEIGHT = 5
CORRECTIONS_TO_RETRAIN = 15
_GENERIC = ("", INDIVIDUAL_PERSON)


@dataclass(frozen=True)
class RetrainResult:
    model: object
    correcoes: int
    linhas_treino: int
    acerto_correcoes_antes: float | None  # % das correções que o modelo anterior já acertava
    acerto_correcoes_depois: float        # % das correções que o modelo novo acerta
    acerto_base_depois: float             # % do CSV base (com os rótulos já substituídos)


def _pct(hits) -> float:
    return round(100 * float(np.mean(hits)), 2) if len(hits) else 0.0


def build_training_set(base: pd.DataFrame, correcoes: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray]:
    """CSV base com os rótulos substituídos + as correções, e o peso de cada linha.
    `correcoes`: colunas do parser + `categoria` + `corrigida_em`."""
    base = base.copy()
    corr = correcoes.sort_values("corrigida_em") if "corrigida_em" in correcoes else correcoes
    corr_key = corr["contraparte"].map(base_name)
    specific = ~corr_key.isin(_GENERIC)
    by_store = dict(zip(corr_key[specific], corr.loc[specific, TARGET]))  # a última correção vence
    if by_store:
        base_key = base["contraparte"].map(base_name)
        to_replace = base_key.isin(list(by_store))
        base.loc[to_replace, TARGET] = base_key[to_replace].map(by_store)
    training = pd.concat([base[[*COLUMNS, TARGET]], corr[[*COLUMNS, TARGET]]], ignore_index=True)
    weights = np.concatenate([np.ones(len(base)), np.full(len(corr), CORRECTION_WEIGHT, dtype=float)])
    return training, weights


def retrain(base, correcoes, current_model=None) -> RetrainResult:
    if base.empty:
        raise ValueError("CSV base de treino vazio")
    if (base[TARGET] == "").any() or (correcoes[TARGET] == "").any():
        raise ValueError("há linhas sem categoria no treino")
    training, weights = build_training_set(base, correcoes)
    X, y = training.drop(columns=[TARGET]), training[TARGET]
    model = build_model().fit(X, y, clf__sample_weight=weights)

    Xc, yc = correcoes[list(COLUMNS)], correcoes[TARGET].to_numpy()
    before = _pct(current_model.predict(Xc) == yc) if current_model is not None and len(correcoes) else None
    n_base = len(training) - len(correcoes)
    return RetrainResult(
        model=model, correcoes=len(correcoes), linhas_treino=len(training),
        acerto_correcoes_antes=before,
        acerto_correcoes_depois=_pct(model.predict(Xc) == yc) if len(correcoes) else 0.0,
        acerto_base_depois=_pct(model.predict(X.iloc[:n_base]) == y.iloc[:n_base].to_numpy()),
    )


def read_base(path) -> pd.DataFrame:
    df = pd.read_csv(path, keep_default_na=False)
    if TARGET not in df.columns:
        raise ValueError(f"o CSV base não tem a coluna {TARGET!r} (gere com python -m ml.label)")
    return df
```

O CSV base precisa estar na máquina que roda a API (fica fora do git). Sem ele, o retreino é
registrado com erro e a correção do usuário continua valendo normalmente.

## 5. Teste do treino

```python
ROWS = [
    # (historico, contraparte, valor, tipo, meio, categoria)
    ("COMPRA NO DÉBITO", "PADARIA FICTICIA", -12.0, "saida", "cartao_debito", "mercado"),
    ("COMPRA NO DÉBITO", "PADARIA MODELO", -8.0, "saida", "cartao_debito", "mercado"),
    ("COMPRA NO DÉBITO", "PADARIA DO BAIRRO", -15.0, "saida", "cartao_debito", "mercado"),
    ("COMPRA NO DÉBITO", "LANCHONETE FICTICIA", -30.0, "saida", "cartao_debito", "alimentacao_fora"),
    ("COMPRA NO DÉBITO", "LANCHONETE MODELO", -25.0, "saida", "cartao_debito", "alimentacao_fora"),
    ("COMPRA NO DÉBITO", "LANCHONETE DO BAIRRO", -28.0, "saida", "cartao_debito", "alimentacao_fora"),
    ("TARIFA", "", -10.0, "saida", "tarifa", "financeiro"),
    ("TARIFA", "", -12.0, "saida", "tarifa", "financeiro"),
    ("PIX RECEBIDO", "PESSOA_FISICA", 100.0, "entrada", "pix", "receitas"),
    ("PIX RECEBIDO", "PESSOA_FISICA", 50.0, "entrada", "pix", "receitas"),
] * 3  # repetido: min_df=3 no TF-IDF e min_frequency=5 no one-hot


def _df():
    return pd.DataFrame([{"id_usuario": "u01", "data": "2024-01-02", "historico": h, "contraparte": c,
                          "valor": v, "tipo": t, "meio": m, "banco": "exemplo", "categoria": cat}
                         for h, c, v, t, m, cat in ROWS])


def test_treina_salva_carrega_e_preve(tmp_path):
    fonte = tmp_path / "rotuladas.csv"
    _df().to_csv(fonte, index=False)
    modelo, n = train_model(fonte)
    joblib.dump(modelo, tmp_path / "m.pkl")
    carregado = joblib.load(tmp_path / "m.pkl")
    novas = pd.DataFrame([
        {"id_usuario": "u99", "data": "2026-11-01", "historico": "COMPRA NO DÉBITO",
         "contraparte": "PADARIA NOVA", "valor": -9.0, "tipo": "saida", "meio": "cartao_debito", "banco": "exemplo"},
        {"id_usuario": "u99", "data": "2026-11-02", "historico": "TARIFA", "contraparte": "",
         "valor": -11.0, "tipo": "saida", "meio": "tarifa", "banco": "outro_banco"},  # banco nunca visto
    ])
    assert list(carregado.predict(novas)) == ["mercado", "financeiro"]
```
