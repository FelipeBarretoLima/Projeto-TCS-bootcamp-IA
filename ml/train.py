"""Trains the final model with ALL of the labeled CSV and saves it as .pkl.

    python -m ml.train
        [--entrada ml/dados/transacoes_rotuladas.csv] [--saida ml/modelos/svm_tfidf.pkl]

Model: linear SVM + character TF-IDF on the counterparty, one-hot on historico/meio/tipo/banco and
log + min-max on the amount (no date). The preprocessing is inside the .pkl: it receives the parser's
CSV as is (contract columns, without `categoria`) and returns the category of each row:

    import joblib, pandas as pd
    model = joblib.load("ml/modelos/svm_tfidf.pkl")
    statement = pd.read_csv("data/teste/u10.csv", keep_default_na=False)
    statement["categoria_prevista"] = model.predict(statement)

The .pkl stays outside git (ml/modelos/): the TF-IDF vocabulary keeps pieces of store names.
It only loads with the same scikit-learn version as requirements.txt.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, MinMaxScaler, OneHotEncoder
from sklearn.svm import LinearSVC

TARGET = "categoria"
CATEGORICAL = ["historico", "meio", "tipo", "banco"]


def build_model() -> Pipeline:
    """Preprocessing + linear SVM. Receives the columns of the parser's CSV."""
    valor = Pipeline([
        # feature_names_out="one-to-one": keeps the column name (to inspect the model weights per feature)
        ("abs", FunctionTransformer(np.abs, feature_names_out="one-to-one")),     # the sign is already in "tipo"
        ("log", FunctionTransformer(np.log1p, feature_names_out="one-to-one")),   # reduces the long tail
        ("minmax", MinMaxScaler()),
    ])
    prep = ColumnTransformer([
        ("contraparte", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=3, sublinear_tf=True),
         "contraparte"),
        ("cat", OneHotEncoder(min_frequency=5, handle_unknown="infrequent_if_exist"), CATEGORICAL),
        ("valor", valor, ["valor"]),
    ])  # the other columns (id_usuario, data) are ignored
    return Pipeline([("prep", prep), ("clf", LinearSVC())])


def train_model(source: Path) -> tuple[Pipeline, int]:
    df = pd.read_csv(source, keep_default_na=False)
    if TARGET not in df.columns:
        raise ValueError(f"a entrada não tem a coluna {TARGET!r}: use o CSV rotulado (python -m ml.label)")
    if (df[TARGET] == "").any():
        raise ValueError("há linhas sem categoria no CSV rotulado")
    model = build_model().fit(df.drop(columns=[TARGET]), df[TARGET])
    return model, len(df)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m ml.train", description="treina e salva o modelo final (.pkl)")
    ap.add_argument("--entrada", dest="source", type=Path, default=Path("ml/dados/transacoes_rotuladas.csv"))
    ap.add_argument("--saida", dest="output", type=Path, default=Path("ml/modelos/svm_tfidf.pkl"))
    args = ap.parse_args(argv)
    try:
        model, rows = train_model(args.source)
    except (OSError, ValueError) as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 3
    args.output.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, args.output)
    print(f"modelo treinado com {rows} linhas e salvo em {args.output}")
    print("classes:", ", ".join(model.classes_))
    return 0


if __name__ == "__main__":
    sys.exit(main())
