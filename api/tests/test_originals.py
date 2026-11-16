"""Original text (not anonymized): encrypted in the database, shown only to the owner, out of ML and chat.

Made-up names.
"""

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from agent import queries
from api import cipher, config
from api.main import app
from api.tests.fakes import OTHER_USER, USER
from statement.models import INDIVIDUAL_PERSON

HEADER = "Data,Valor,Identificador,Descrição\n"
PIX = ("02/01/2024,-50.00,11111111-2222-4333-8444-555555555555,Transferência enviada pelo Pix - "
       "ZEFERINO INVENTADO SILVA - •••.123.456-•• - BANCO FICTICIO (0001) Agência: 1 Conta: 123-4\n")
CARD = "03/01/2024,-12.50,11111111-2222-4333-8444-555555555556,Compra no débito - IFOOD *PIZZARIA IMAGINARIA\n"


def _upload():
    return TestClient(app).post("/api/extratos", files={"arquivo": ("e.csv", (HEADER + PIX + CARD).encode())})


# --- cipher ---

def test_encrypt_and_decrypt():
    original = {"historico": "PIX ENVIADO", "contraparte": "ZEFERINO INVENTADO SILVA"}
    text = cipher.encrypt(original)
    assert "ZEFERINO" not in text
    assert cipher.decrypt(text) == original


def test_without_key_neither_encrypts_nor_decrypts(monkeypatch):
    text = cipher.encrypt({"historico": "", "contraparte": "X"})
    monkeypatch.setattr(config, "ORIGINALS_KEY", "")
    assert not cipher.enabled()
    assert cipher.encrypt({"historico": "", "contraparte": "X"}) is None
    assert cipher.decrypt(text) is None


def test_different_key_does_not_open_and_does_not_break(monkeypatch):
    text = cipher.encrypt({"historico": "", "contraparte": "X"})
    monkeypatch.setattr(config, "ORIGINALS_KEY", Fernet.generate_key().decode())
    assert cipher.decrypt(text) is None


def test_malformed_key_is_a_clear_error(monkeypatch):
    monkeypatch.setattr(config, "ORIGINALS_KEY", "nao-e-uma-chave")
    with pytest.raises(cipher.InvalidKey, match="--nova-chave"):
        cipher.encrypt({"historico": "", "contraparte": "X"})


# --- import and Extrato tab ---

def test_import_returns_the_original_and_saves_it_only_encrypted(db):
    r = _upload()
    assert r.status_code == 200
    pix, card = r.json()["transacoes"]
    assert (pix["contraparte"], pix["contraparte_original"]) == (INDIVIDUAL_PERSON, "ZEFERINO INVENTADO SILVA")
    assert (card["contraparte"], card["contraparte_original"]) == ("IFOOD", "IFOOD *PIZZARIA IMAGINARIA")
    assert "123.456" not in str(r.json())  # the CPF does not go in even in the original

    saved = db.transactions(USER.id)
    assert {t["contraparte"] for t in saved} == {INDIVIDUAL_PERSON, "IFOOD"}
    for t in saved:
        assert t["original_cifrado"] and "ZEFERINO" not in t["original_cifrado"]
        assert "PIZZARIA" not in t["original_cifrado"]
        assert "contraparte_original" not in t and "historico_original" not in t


def test_extrato_tab_shows_the_decrypted_original():
    _upload()
    [card, pix] = TestClient(app).get("/api/transacoes").json()  # most recent first
    assert (pix["contraparte"], pix["contraparte_original"]) == (INDIVIDUAL_PERSON, "ZEFERINO INVENTADO SILVA")
    assert card["contraparte_original"] == "IFOOD *PIZZARIA IMAGINARIA"
    assert "original_cifrado" not in pix


def test_another_user_does_not_see_the_originals(logged_in_as):
    _upload()
    logged_in_as(OTHER_USER)
    assert TestClient(app).get("/api/transacoes").json() == []


def test_without_key_imports_normally_and_extrato_shows_the_anonymized_text(db, monkeypatch):
    monkeypatch.setattr(config, "ORIGINALS_KEY", "")
    r = _upload()
    assert r.status_code == 200
    assert r.json()["transacoes"][0]["contraparte_original"] == "ZEFERINO INVENTADO SILVA"  # only in the response
    assert all(t["original_cifrado"] is None for t in db.transactions(USER.id))
    pix = TestClient(app).get("/api/transacoes").json()[1]
    assert (pix["contraparte"], pix["contraparte_original"]) == (INDIVIDUAL_PERSON, None)


def test_malformed_key_on_import_gives_500_without_saving(db, monkeypatch):
    monkeypatch.setattr(config, "ORIGINALS_KEY", "nao-e-uma-chave")
    r = _upload()
    assert r.status_code == 500 and "CHAVE_ORIGINAIS" in r.json()["detail"]
    assert db.transactions(USER.id) == []


def test_chat_and_ml_only_see_the_anonymized_text(db):
    _upload()
    df = queries.to_dataframe(db.transactions(USER.id))
    assert "original_cifrado" not in df.columns
    assert set(df["contraparte"]) == {INDIVIDUAL_PERSON, "IFOOD"}
