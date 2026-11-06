"""Categoria na API (regras + mapa). Dados inventados."""

import csv
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from api.esquemas import Relatorio, ResultadoUpload, Transacao
from api.main import app
from api.servicos.categorizacao import categoriza
from extrato.modelos import PESSOA_FISICA
from ml import rotular

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
