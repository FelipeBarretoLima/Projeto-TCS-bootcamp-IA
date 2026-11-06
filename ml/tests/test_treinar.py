"""Modelo final: treinar, salvar, carregar e prever com o CSV do parser. Dados inventados."""

import joblib
import pandas as pd

from extrato.modelos import COLUNAS
from ml.treinar import monta_modelo, treina

LINHAS = [
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


def _df(com_categoria=True):
    linhas = [{"id_usuario": "u01", "data": "2024-01-02", "historico": h, "contraparte": c, "valor": v,
               "tipo": t, "meio": m, "banco": "exemplo", "categoria": cat} for h, c, v, t, m, cat in LINHAS]
    df = pd.DataFrame(linhas)
    return df if com_categoria else df[list(COLUNAS)]


def test_treina_salva_carrega_e_preve_com_o_csv_do_parser(tmp_path):
    entrada = tmp_path / "rotuladas.csv"
    _df().to_csv(entrada, index=False)
    modelo, n = treina(entrada)
    assert n == len(LINHAS)
    joblib.dump(modelo, tmp_path / "m.pkl")
    carregado = joblib.load(tmp_path / "m.pkl")
    novo = pd.DataFrame([
        {"id_usuario": "u99", "data": "2026-11-01", "historico": "COMPRA NO DÉBITO", "contraparte": "PADARIA NOVA",
         "valor": -9.0, "tipo": "saida", "meio": "cartao_debito", "banco": "exemplo"},
        {"id_usuario": "u99", "data": "2026-11-02", "historico": "TARIFA", "contraparte": "",
         "valor": -11.0, "tipo": "saida", "meio": "tarifa", "banco": "outro_banco"},  # banco nunca visto
    ])
    assert list(carregado.predict(novo)) == ["mercado", "financeiro"]


def test_modelo_ignora_id_usuario_e_data():
    m = monta_modelo().fit(_df(False), _df()["categoria"])
    a = _df(False).head(4)
    b = a.assign(id_usuario="u55", data="2030-12-31")
    assert list(m.predict(a)) == list(m.predict(b))
