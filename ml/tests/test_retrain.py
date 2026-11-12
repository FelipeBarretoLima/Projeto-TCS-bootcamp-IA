"""Retraining with users' corrections (made-up data)."""

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from statement.models import COLUMNS, INDIVIDUAL_PERSON
from ml.retrain import CORRECTION_WEIGHT, build_training_set, retrain

_T0 = datetime(2026, 11, 1, tzinfo=timezone.utc)


def _row(contraparte, categoria, meio="cartao_debito", historico="COMPRA", valor=-10.0, i=0):
    return dict(id_usuario="u01", data="2024-01-02", historico=historico, contraparte=contraparte,
                valor=valor - i, tipo="saida", meio=meio, banco="banco_teste", categoria=categoria)


def _base():
    """Made-up stores per category + PIX to a person, with enough repetitions for TF-IDF."""
    stores = {"mercado": ["SUPERMERCADO FICTICIO", "MERCADINHO INVENTADO"],
             "transporte": ["POSTO INVENTADO", "AUTO POSTO IMAGINARIO"],
             "alimentacao_fora": ["PIZZARIA IMAGINARIA", "LANCHONETE FICTICIA"],
             "compras": ["LOJA DE ROUPAS X", "MAGAZINE INVENTADO", "UNIVERSIDADE FICTICIA DO SUL"]}
    rows = [_row(name, cat, i=i) for cat, names in stores.items() for name in names for i in range(8)]
    rows += [_row(INDIVIDUAL_PERSON, "transferencia_pessoa", "pix", "PIX ENVIADO", i=i) for i in range(10)]
    return pd.DataFrame(rows)


def _corrections(*entries):
    rows = [{**_row(c, cat, meio, hist, valor=-4.7), "corrigida_em": _T0 + timedelta(minutes=n)}
              for n, (c, cat, meio, hist) in enumerate(entries)]
    return pd.DataFrame(rows, columns=[*COLUMNS, "categoria", "corrigida_em"])


def test_correction_replaces_same_store_label_and_weighs_more():
    base = _base()
    corr = _corrections(("UNIVERSIDADE FICTICIA DO SUL", "alimentacao_fora", "pix", "PIX ENVIADO"))
    training, weights = build_training_set(base, corr)
    for_store = training[training["contraparte"] == "UNIVERSIDADE FICTICIA DO SUL"]
    assert set(for_store["categoria"]) == {"alimentacao_fora"}  # the 8 from the base CSV + the correction
    assert len(training) == len(base) + 1 and weights[-1] == CORRECTION_WEIGHT and weights[:-1].max() == 1


def test_correction_on_pix_to_person_does_not_change_other_pix():
    corr = _corrections((INDIVIDUAL_PERSON, "alimentacao_fora", "pix", "PIX ENVIADO"))
    training, _ = build_training_set(_base(), corr)
    pix_base = training.iloc[:-1][training.iloc[:-1]["contraparte"] == INDIVIDUAL_PERSON]
    assert set(pix_base["categoria"]) == {"transferencia_pessoa"}


def test_conflicting_corrections_latest_wins():
    corr = _corrections(("MAGAZINE INVENTADO", "mercado", "cartao_debito", "COMPRA"),
                      ("MAGAZINE INVENTADO", "contas_servicos", "cartao_debito", "COMPRA"))
    training, _ = build_training_set(_base(), corr)
    store_base = training.iloc[:-2][training.iloc[:-2]["contraparte"] == "MAGAZINE INVENTADO"]
    assert set(store_base["categoria"]) == {"contas_servicos"}


def test_new_model_learns_correction():
    base = _base()
    corr = _corrections(("UNIVERSIDADE FICTICIA DO SUL", "alimentacao_fora", "pix", "PIX ENVIADO"))
    before = retrain(base, corr.iloc[0:0]).model  # model without the correction
    r = retrain(base, corr, current_model=before)
    assert r.acerto_correcoes_antes == 0.0 and r.acerto_correcoes_depois == 100.0
    assert r.correcoes == 1 and r.linhas_treino == len(base) + 1 and r.acerto_base_depois > 90
    new_row = corr[list(COLUMNS)].assign(valor=-9.0)  # another purchase at the same store
    assert r.model.predict(new_row)[0] == "alimentacao_fora"


def test_no_current_model_no_before_and_empty_base_is_error():
    r = retrain(_base(), _corrections(("POSTO INVENTADO", "transporte", "cartao_debito", "COMPRA")))
    assert r.acerto_correcoes_antes is None
    with pytest.raises(ValueError, match="vazio"):
        retrain(_base().iloc[0:0], _corrections())
