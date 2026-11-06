"""Treina o modelo final com TODO o CSV rotulado e salva em .pkl.

    python -m ml.treinar
        [--entrada ml/dados/transacoes_rotuladas.csv] [--saida ml/modelos/svm_tfidf.pkl]

Modelo: SVM linear + TF-IDF de caracteres na contraparte, one-hot em historico/meio/tipo/banco e
log + min-max no valor (sem data). O pré-processamento está dentro do .pkl: ele recebe o CSV do
parser como está (colunas do contrato, sem `categoria`) e devolve a categoria de cada linha:

    import joblib, pandas as pd
    modelo = joblib.load("ml/modelos/svm_tfidf.pkl")
    extrato = pd.read_csv("data/teste/u10.csv", keep_default_na=False)
    extrato["categoria_prevista"] = modelo.predict(extrato)

O .pkl fica fora do git (ml/modelos/): o vocabulário do TF-IDF guarda pedaços dos nomes das lojas.
Ele só carrega com a mesma versão do scikit-learn do requirements.txt.
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

ALVO = "categoria"
CATEGORICAS = ["historico", "meio", "tipo", "banco"]


def monta_modelo() -> Pipeline:
    """Pré-processamento + SVM linear. Recebe as colunas do CSV do parser."""
    valor = Pipeline([
        # feature_names_out="one-to-one": mantém o nome da coluna (para ver os pesos do modelo por atributo)
        ("abs", FunctionTransformer(np.abs, feature_names_out="one-to-one")),     # o sinal já está em "tipo"
        ("log", FunctionTransformer(np.log1p, feature_names_out="one-to-one")),   # reduz a cauda longa
        ("minmax", MinMaxScaler()),
    ])
    prep = ColumnTransformer([
        ("contraparte", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=3, sublinear_tf=True),
         "contraparte"),
        ("cat", OneHotEncoder(min_frequency=5, handle_unknown="infrequent_if_exist"), CATEGORICAS),
        ("valor", valor, ["valor"]),
    ])  # as demais colunas (id_usuario, data) são ignoradas
    return Pipeline([("prep", prep), ("clf", LinearSVC())])


def treina(entrada: Path) -> tuple[Pipeline, int]:
    df = pd.read_csv(entrada, keep_default_na=False)
    if ALVO not in df.columns:
        raise ValueError(f"a entrada não tem a coluna {ALVO!r}: use o CSV rotulado (python -m ml.rotular)")
    if (df[ALVO] == "").any():
        raise ValueError("há linhas sem categoria no CSV rotulado")
    modelo = monta_modelo().fit(df.drop(columns=[ALVO]), df[ALVO])
    return modelo, len(df)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m ml.treinar", description="treina e salva o modelo final (.pkl)")
    ap.add_argument("--entrada", type=Path, default=Path("ml/dados/transacoes_rotuladas.csv"))
    ap.add_argument("--saida", type=Path, default=Path("ml/modelos/svm_tfidf.pkl"))
    args = ap.parse_args(argv)
    try:
        modelo, linhas = treina(args.entrada)
    except (OSError, ValueError) as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 3
    args.saida.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(modelo, args.saida)
    print(f"modelo treinado com {linhas} linhas e salvo em {args.saida}")
    print("classes:", ", ".join(modelo.classes_))
    return 0


if __name__ == "__main__":
    sys.exit(main())
