"""Final model: train, save, load and predict with the parser's CSV. Made-up data."""

import joblib
import pandas as pd

from statement.models import COLUMNS
from ml.train import build_model, train_model

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
] * 3


def _df(with_category=True):
    rows = [{"id_usuario": "u01", "data": "2024-01-02", "historico": h, "contraparte": c, "valor": v,
               "tipo": t, "meio": m, "banco": "exemplo", "categoria": cat} for h, c, v, t, m, cat in ROWS]
    df = pd.DataFrame(rows)
    return df if with_category else df[list(COLUMNS)]


def test_train_save_load_and_predict_with_parser_csv(tmp_path):
    source = tmp_path / "rotuladas.csv"
    _df().to_csv(source, index=False)
    model, n = train_model(source)
    assert n == len(ROWS)
    joblib.dump(model, tmp_path / "m.pkl")
    loaded = joblib.load(tmp_path / "m.pkl")
    new = pd.DataFrame([
        {"id_usuario": "u99", "data": "2026-11-01", "historico": "COMPRA NO DÉBITO", "contraparte": "PADARIA NOVA",
         "valor": -9.0, "tipo": "saida", "meio": "cartao_debito", "banco": "exemplo"},
        {"id_usuario": "u99", "data": "2026-11-02", "historico": "TARIFA", "contraparte": "",
         "valor": -11.0, "tipo": "saida", "meio": "tarifa", "banco": "outro_banco"},  # never-seen bank
    ])
    assert list(loaded.predict(new)) == ["mercado", "financeiro"]


def test_model_ignores_user_id_and_date():
    m = build_model().fit(_df(False), _df()["categoria"])
    a = _df(False).head(4)
    b = a.assign(id_usuario="u55", data="2030-12-31")
    assert list(m.predict(a)) == list(m.predict(b))
