"""Texto original (sem anonimizar): cifrado no banco, mostrado só ao dono, fora do ML e do chat.

Nomes inventados.
"""

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from agente import consultas
from api import cifra, config
from api.main import app
from api.tests.falsos import OUTRO, USUARIO
from extrato.modelos import PESSOA_FISICA

CAB = "Data,Valor,Identificador,Descrição\n"
PIX = ("02/01/2024,-50.00,11111111-2222-4333-8444-555555555555,Transferência enviada pelo Pix - "
       "ZEFERINO INVENTADO SILVA - •••.123.456-•• - BANCO FICTICIO (0001) Agência: 1 Conta: 123-4\n")
CARTAO = "03/01/2024,-12.50,11111111-2222-4333-8444-555555555556,Compra no débito - IFOOD *PIZZARIA IMAGINARIA\n"


def _envia():
    return TestClient(app).post("/api/extratos", files={"arquivo": ("e.csv", (CAB + PIX + CARTAO).encode())})


# --- cifra ---

def test_cifra_e_decifra():
    original = {"historico": "PIX ENVIADO", "contraparte": "ZEFERINO INVENTADO SILVA"}
    texto = cifra.cifra(original)
    assert "ZEFERINO" not in texto
    assert cifra.decifra(texto) == original


def test_sem_chave_nao_cifra_nem_decifra(monkeypatch):
    texto = cifra.cifra({"historico": "", "contraparte": "X"})
    monkeypatch.setattr(config, "CHAVE_ORIGINAIS", "")
    assert not cifra.ativa()
    assert cifra.cifra({"historico": "", "contraparte": "X"}) is None
    assert cifra.decifra(texto) is None


def test_chave_diferente_nao_abre_e_nao_quebra(monkeypatch):
    texto = cifra.cifra({"historico": "", "contraparte": "X"})
    monkeypatch.setattr(config, "CHAVE_ORIGINAIS", Fernet.generate_key().decode())
    assert cifra.decifra(texto) is None


def test_chave_mal_formada_e_erro_claro(monkeypatch):
    monkeypatch.setattr(config, "CHAVE_ORIGINAIS", "nao-e-uma-chave")
    with pytest.raises(cifra.ChaveInvalida, match="--nova-chave"):
        cifra.cifra({"historico": "", "contraparte": "X"})


# --- importação e aba Extrato ---

def test_importacao_devolve_original_e_grava_so_cifrado(db):
    r = _envia()
    assert r.status_code == 200
    pix, cartao = r.json()["transacoes"]
    assert (pix["contraparte"], pix["contraparte_original"]) == (PESSOA_FISICA, "ZEFERINO INVENTADO SILVA")
    assert (cartao["contraparte"], cartao["contraparte_original"]) == ("IFOOD", "IFOOD *PIZZARIA IMAGINARIA")
    assert "123.456" not in str(r.json())  # o CPF não entra nem no original

    gravadas = db.transacoes(USUARIO.id)
    assert {t["contraparte"] for t in gravadas} == {PESSOA_FISICA, "IFOOD"}
    for t in gravadas:
        assert t["original_cifrado"] and "ZEFERINO" not in t["original_cifrado"]
        assert "PIZZARIA" not in t["original_cifrado"]
        assert "contraparte_original" not in t and "historico_original" not in t


def test_aba_extrato_mostra_o_original_decifrado():
    _envia()
    [cartao, pix] = TestClient(app).get("/api/transacoes").json()  # mais recente primeiro
    assert (pix["contraparte"], pix["contraparte_original"]) == (PESSOA_FISICA, "ZEFERINO INVENTADO SILVA")
    assert cartao["contraparte_original"] == "IFOOD *PIZZARIA IMAGINARIA"
    assert "original_cifrado" not in pix


def test_outro_usuario_nao_ve_os_originais(logado_como):
    _envia()
    logado_como(OUTRO)
    assert TestClient(app).get("/api/transacoes").json() == []


def test_sem_chave_importa_normal_e_extrato_mostra_o_anonimizado(db, monkeypatch):
    monkeypatch.setattr(config, "CHAVE_ORIGINAIS", "")
    r = _envia()
    assert r.status_code == 200
    assert r.json()["transacoes"][0]["contraparte_original"] == "ZEFERINO INVENTADO SILVA"  # só na resposta
    assert all(t["original_cifrado"] is None for t in db.transacoes(USUARIO.id))
    pix = TestClient(app).get("/api/transacoes").json()[1]
    assert (pix["contraparte"], pix["contraparte_original"]) == (PESSOA_FISICA, None)


def test_chave_mal_formada_na_importacao_da_500_sem_gravar(db, monkeypatch):
    monkeypatch.setattr(config, "CHAVE_ORIGINAIS", "nao-e-uma-chave")
    r = _envia()
    assert r.status_code == 500 and "CHAVE_ORIGINAIS" in r.json()["detail"]
    assert db.transacoes(USUARIO.id) == []


def test_chat_e_ml_so_veem_o_anonimizado(db):
    _envia()
    df = consultas.tabela(db.transacoes(USUARIO.id))
    assert "original_cifrado" not in df.columns
    assert set(df["contraparte"]) == {PESSOA_FISICA, "IFOOD"}
