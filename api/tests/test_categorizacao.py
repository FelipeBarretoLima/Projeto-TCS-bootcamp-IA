"""Categoria na API (regras + mapa + classificador). Dados inventados."""

import csv
from datetime import date
from decimal import Decimal

import joblib
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from api import config
from api.esquemas import Relatorio, ResultadoUpload, Transacao
from api.main import app
from api.servicos import categorizacao
from api.servicos.categorizacao import categoriza
from extrato.modelos import COLUNAS, PESSOA_FISICA
from ml import rotular
from ml.treinar import monta_modelo

CAB = "Data,Valor,Identificador,Descrição\n"
U1 = "11111111-2222-4333-8444-555555555555"


def _grava_mapa(pasta, linhas):
    with open(pasta / rotular.ARQ_REVISADO, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rotular.COLUNAS_MAPA, lineterminator="\n")
        w.writeheader()
        for l in linhas:
            w.writerow({c: l.get(c, "") for c in rotular.COLUNAS_MAPA})


def _transacao(meio, tipo, historico, contraparte, valor="-10.00"):
    return Transacao(data=date(2024, 1, 2), historico=historico, contraparte=contraparte,
                     valor=Decimal(valor), tipo=tipo, meio=meio, banco="banco_teste")


def _resultado(*transacoes):
    relatorio = Relatorio(status="aceito", motivo="", parser="p", periodo_inicio="", periodo_fim="",
                          linhas_extraidas=0, linhas_gravadas=0, linhas_revisar=0,
                          linhas_duplicadas=0, linhas_omitidas=0, reconciliacao="ok")
    return ResultadoUpload(relatorio=relatorio, transacoes=list(transacoes))


CASOS = [
    _transacao("tarifa", "saida", "TARIFA", ""),
    _transacao("pix", "entrada", "PIX RECEBIDO", PESSOA_FISICA, "50.00"),
    _transacao("pix", "saida", "PIX ENVIADO", PESSOA_FISICA),
    _transacao("boleto", "saida", "PAGAMENTO DE BOLETO", ""),
    _transacao("cartao_debito", "saida", "COMPRA", "PADARIA MODELO"),
    _transacao("cartao_credito", "saida", "COMPRA", "LOJA INVENTADA"),
    _transacao("pix", "saida", "PIX ENVIADO", "EMPRESA FICTICIA LTDA"),
]


def test_mesma_categoria_que_o_modulo_ml(dir_privado):
    _grava_mapa(dir_privado, [{"contraparte": "PADARIA MODELO", "classe": "mercado"}])
    mapa = rotular.carrega_mapa(dir_privado)
    resultado = categoriza(_resultado(*CASOS))
    for t in resultado.transacoes:
        esperado = rotular.categoria(t.model_dump(mode="json"), mapa)
        assert t.categoria == (esperado.value if esperado else None)


def test_origem_da_categoria(dir_privado):
    _grava_mapa(dir_privado, [{"contraparte": "PADARIA MODELO", "classe": "mercado"}])
    tarifa, _, _, _, padaria, loja, empresa = categoriza(_resultado(*CASOS)).transacoes
    assert (tarifa.categoria, tarifa.origem_categoria) == ("financeiro", "regra")
    assert (padaria.categoria, padaria.origem_categoria) == ("mercado", "mapa")
    assert (loja.categoria, loja.origem_categoria) == (None, None)
    assert (empresa.categoria, empresa.origem_categoria) == (None, None)


def test_conta_sem_categoria():
    # sem mapa: só as 4 primeiras (regras) têm categoria
    assert categoriza(_resultado(*CASOS)).sem_categoria == 3


def test_upload_devolve_categoria(dir_privado):
    _grava_mapa(dir_privado, [{"contraparte": "PADARIA MODELO", "classe": "mercado"}])
    csv_ = (f"{CAB}02/01/2024,-12.50,{U1},Compra no débito - PADARIA MODELO\n").encode()
    r = TestClient(app).post("/api/extratos", files={"arquivo": ("e.csv", csv_)})
    assert r.status_code == 200
    corpo = r.json()
    [t] = corpo["transacoes"]
    assert (t["categoria"], t["origem_categoria"]) == ("mercado", "mapa")
    assert corpo["sem_categoria"] == 0


def test_mapa_com_classe_invalida_vira_erro_500(dir_privado):
    _grava_mapa(dir_privado, [{"contraparte": "PADARIA MODELO", "classe": "nao_existe"}])
    csv_ = (f"{CAB}02/01/2024,-12.50,{U1},Compra no débito - PADARIA MODELO\n").encode()
    r = TestClient(app).post("/api/extratos", files={"arquivo": ("e.csv", csv_)})
    assert r.status_code == 500
    assert "linha 2" in r.json()["detail"]
    assert "PADARIA" not in r.json()["detail"]


# --- classificador (passo 3) ---

class _ModeloFalso:
    """Devolve sempre a mesma classe e guarda o que recebeu."""

    def __init__(self, classe):
        self.classe, self.recebido = classe, None

    def predict(self, df):
        self.recebido = df
        return [self.classe] * len(df)


def test_modelo_so_preenche_o_que_regra_e_mapa_nao_resolveram(dir_privado, monkeypatch):
    _grava_mapa(dir_privado, [{"contraparte": "PADARIA MODELO", "classe": "mercado"}])
    falso = _ModeloFalso("compras")
    monkeypatch.setattr(categorizacao, "carrega_modelo", lambda caminho: falso)
    resultado = categoriza(_resultado(*CASOS))
    tarifa, _, _, _, padaria, loja, empresa = resultado.transacoes
    assert (tarifa.categoria, tarifa.origem_categoria) == ("financeiro", "regra")
    assert (padaria.categoria, padaria.origem_categoria) == ("mercado", "mapa")
    assert (loja.categoria, loja.origem_categoria) == ("compras", "modelo")
    assert (empresa.categoria, empresa.origem_categoria) == ("compras", "modelo")
    assert resultado.sem_categoria == 0
    # o modelo recebe só as pendentes, com as colunas do CSV do parser e o valor numérico
    assert list(falso.recebido.columns) == list(COLUNAS)
    assert list(falso.recebido["contraparte"]) == ["LOJA INVENTADA", "EMPRESA FICTICIA LTDA"]
    assert falso.recebido["valor"].dtype == float


def test_sem_pendentes_o_modelo_nao_e_chamado(monkeypatch):
    falso = _ModeloFalso("compras")
    monkeypatch.setattr(categorizacao, "carrega_modelo", lambda caminho: falso)
    categoriza(_resultado(CASOS[0]))
    assert falso.recebido is None


def test_carrega_modelo_ausente_ou_corrompido(tmp_path):
    assert categorizacao.carrega_modelo(tmp_path / "nao_existe.pkl") is None
    quebrado = tmp_path / "quebrado.pkl"
    quebrado.write_bytes(b"isto nao e um pickle")
    assert categorizacao.carrega_modelo(quebrado) is None


def _treina_pkl(caminho):
    """Modelo de verdade (o mesmo pipeline do ml.treinar), com dados inventados."""
    lojas = {"mercado": "SUPERMERCADO FICTICIO", "transporte": "POSTO INVENTADO",
             "alimentacao_fora": "PIZZARIA IMAGINARIA"}
    linhas = [dict(id_usuario="u01", data="2024-01-02", historico="COMPRA", contraparte=f"{nome} {i}",
                   valor=-10.0 - i, tipo="saida", meio="cartao_credito", banco="banco_teste", categoria=cat)
              for cat, nome in lojas.items() for i in range(10)]
    df = pd.DataFrame(linhas)
    joblib.dump(monta_modelo().fit(df.drop(columns=["categoria"]), df["categoria"]), caminho)


def test_upload_com_modelo_real(tmp_path, monkeypatch):
    caminho = tmp_path / "modelo.pkl"
    _treina_pkl(caminho)
    monkeypatch.setattr(config, "CAMINHO_MODELO", caminho)
    csv_ = (f"{CAB}02/01/2024,-12.50,{U1},Compra no débito - PIZZARIA IMAGINARIA\n").encode()
    r = TestClient(app).post("/api/extratos", files={"arquivo": ("e.csv", csv_)})
    assert r.status_code == 200
    [t] = r.json()["transacoes"]
    assert (t["categoria"], t["origem_categoria"]) == ("alimentacao_fora", "modelo")
    assert r.json()["sem_categoria"] == 0
