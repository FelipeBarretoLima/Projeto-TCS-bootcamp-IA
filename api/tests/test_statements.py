"""Upload route with made-up files (no real data)."""

import pytest
from fastapi.testclient import TestClient

from api.main import app

HEADER = "Data,Valor,Identificador,Descrição\n"
U1 = "11111111-2222-4333-8444-555555555555"

client = TestClient(app)


def _upload(name: str, content: bytes, **form: str):
    return client.post("/api/extratos", files={"arquivo": (name, content)}, data=form)


def test_accepted_nubank_csv_returns_transactions():
    csv = f"{HEADER}02/01/2024,-12.50,{U1},Compra no débito - PADARIA MODELO\n".encode()
    r = _upload("meu extrato.csv", csv)
    assert r.status_code == 200
    body = r.json()
    assert body["relatorio"]["status"] == "aceito"
    assert body["relatorio"]["parser"] == "nubank_conta_csv"
    assert body["relatorio"]["linhas_gravadas"] == 1
    [t] = body["transacoes"]
    assert t["data"] == "2024-01-02"
    assert t["valor"] == "-12.50"
    assert (t["tipo"], t["meio"], t["banco"]) == ("saida", "cartao_debito", "nubank")
    assert "id_usuario" not in t


def test_unrecognized_file_comes_back_rejected():
    r = _upload("planilha.csv", b"a,b,c\n1,2,3\n")
    assert r.status_code == 200
    body = r.json()
    assert body["relatorio"]["status"] == "rejeitado"
    assert body["relatorio"]["motivo"] == "FormatoNaoReconhecido"
    assert body["transacoes"] == []


@pytest.mark.parametrize("name", ["extrato.txt", "extrato", "extrato.xlsx"])
def test_invalid_extension(name):
    r = _upload(name, b"qualquer coisa")
    assert r.status_code == 400
    assert "formato" in r.json()["detail"]


@pytest.mark.parametrize("pseudonym", ["07", "u7", "u123", "x01"])
def test_invalid_pseudonym(pseudonym):
    r = _upload("extrato.csv", b"x", usuario=pseudonym)
    assert r.status_code == 400


def test_empty_file():
    assert _upload("extrato.pdf", b"").status_code == 400


def test_file_too_large(monkeypatch):
    from api.routes import statements

    monkeypatch.setattr(statements, "MAX_SIZE", 10)
    assert _upload("extrato.csv", b"x" * 11).status_code == 400
