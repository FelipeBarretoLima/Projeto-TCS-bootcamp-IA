"""Rota de upload com arquivos inventados (nenhum dado real)."""

import pytest
from fastapi.testclient import TestClient

from api.main import app

CAB = "Data,Valor,Identificador,Descrição\n"
U1 = "11111111-2222-4333-8444-555555555555"

cliente = TestClient(app)


def _envia(nome: str, conteudo: bytes, **form: str):
    return cliente.post("/api/extratos", files={"arquivo": (nome, conteudo)}, data=form)


def test_csv_nubank_aceito_devolve_transacoes():
    csv = f"{CAB}02/01/2024,-12.50,{U1},Compra no débito - PADARIA MODELO\n".encode()
    r = _envia("meu extrato.csv", csv)
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["relatorio"]["status"] == "aceito"
    assert corpo["relatorio"]["parser"] == "nubank_conta_csv"
    assert corpo["relatorio"]["linhas_gravadas"] == 1
    [t] = corpo["transacoes"]
    assert t["data"] == "2024-01-02"
    assert t["valor"] == "-12.50"
    assert (t["tipo"], t["meio"], t["banco"]) == ("saida", "cartao_debito", "nubank")
    assert "id_usuario" not in t


def test_arquivo_nao_reconhecido_vem_rejeitado():
    r = _envia("planilha.csv", b"a,b,c\n1,2,3\n")
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["relatorio"]["status"] == "rejeitado"
    assert corpo["relatorio"]["motivo"] == "FormatoNaoReconhecido"
    assert corpo["transacoes"] == []


@pytest.mark.parametrize("nome", ["extrato.txt", "extrato", "extrato.xlsx"])
def test_extensao_invalida(nome):
    r = _envia(nome, b"qualquer coisa")
    assert r.status_code == 400
    assert "formato" in r.json()["detail"]


@pytest.mark.parametrize("usuario", ["07", "u7", "u123", "x01"])
def test_usuario_invalido(usuario):
    r = _envia("extrato.csv", b"x", usuario=usuario)
    assert r.status_code == 400


def test_arquivo_vazio():
    assert _envia("extrato.pdf", b"").status_code == 400


def test_arquivo_grande_demais(monkeypatch):
    from api.routes import statements

    monkeypatch.setattr(statements, "TAMANHO_MAXIMO", 10)
    assert _envia("extrato.csv", b"x" * 11).status_code == 400
