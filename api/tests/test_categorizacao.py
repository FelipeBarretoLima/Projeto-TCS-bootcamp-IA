"""Categoria na API: entradas = receitas (regra), saídas = classificador. Dados inventados."""

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


def test_entrada_e_receita_por_regra_e_saida_sem_modelo_fica_sem_categoria():
    tarifa, pix_recebido, *saidas = categoriza(_resultado(*CASOS)).transacoes
    assert (pix_recebido.categoria, pix_recebido.origem_categoria) == ("receitas", "regra")
    # sem o .pkl, nenhuma saída tem categoria: nem a tarifa, que antes era regra fixa
    assert all((t.categoria, t.origem_categoria) == (None, None) for t in [tarifa, *saidas])


def test_conta_sem_categoria():
    assert categoriza(_resultado(*CASOS)).sem_categoria == 6  # só a entrada tem categoria


def test_mapa_de_estabelecimentos_nao_e_usado_na_api(dir_privado):
    # o mapa só gera rótulos para o treino; na API quem decide as saídas é o modelo
    _grava_mapa(dir_privado, [{"contraparte": "PADARIA MODELO", "classe": "mercado"}])
    csv_ = (f"{CAB}02/01/2024,-12.50,{U1},Compra no débito - PADARIA MODELO\n").encode()
    r = TestClient(app).post("/api/extratos", files={"arquivo": ("e.csv", csv_)})
    assert r.status_code == 200
    [t] = r.json()["transacoes"]
    assert (t["categoria"], t["origem_categoria"]) == (None, None)
    assert r.json()["sem_categoria"] == 1


def test_mapa_invalido_nao_derruba_a_importacao(dir_privado):
    _grava_mapa(dir_privado, [{"contraparte": "PADARIA MODELO", "classe": "nao_existe"}])
    csv_ = (f"{CAB}02/01/2024,-12.50,{U1},Compra no débito - PADARIA MODELO\n").encode()
    assert TestClient(app).post("/api/extratos", files={"arquivo": ("e.csv", csv_)}).status_code == 200


# --- classificador (todas as saídas) ---

class _ModeloFalso:
    """Devolve sempre a mesma classe e guarda o que recebeu."""

    def __init__(self, classe):
        self.classe, self.recebido = classe, None

    def predict(self, df):
        self.recebido = df
        return [self.classe] * len(df)


def test_modelo_classifica_todas_as_saidas_e_nunca_as_entradas(dir_privado, monkeypatch):
    _grava_mapa(dir_privado, [{"contraparte": "PADARIA MODELO", "classe": "mercado"}])  # ignorado
    falso = _ModeloFalso("compras")
    monkeypatch.setattr(categorizacao, "carrega_modelo", lambda caminho: falso)
    resultado = categoriza(_resultado(*CASOS))
    tarifa, pix_recebido, pix_enviado, boleto, padaria, loja, empresa = resultado.transacoes
    assert (pix_recebido.categoria, pix_recebido.origem_categoria) == ("receitas", "regra")
    for t in (tarifa, pix_enviado, boleto, padaria, loja, empresa):
        assert (t.categoria, t.origem_categoria) == ("compras", "modelo")
    assert resultado.sem_categoria == 0
    # o modelo recebe só as saídas, com as colunas do CSV do parser e o valor numérico
    assert list(falso.recebido.columns) == list(COLUNAS)
    assert list(falso.recebido["tipo"]) == ["saida"] * 6
    assert list(falso.recebido["contraparte"]) == [
        "", PESSOA_FISICA, "", "PADARIA MODELO", "LOJA INVENTADA", "EMPRESA FICTICIA LTDA"]
    assert falso.recebido["valor"].dtype == float


def test_so_entradas_o_modelo_nao_e_chamado(monkeypatch):
    falso = _ModeloFalso("compras")
    monkeypatch.setattr(categorizacao, "carrega_modelo", lambda caminho: falso)
    categoriza(_resultado(CASOS[1]))
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
