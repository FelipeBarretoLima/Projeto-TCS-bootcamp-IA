"""Mensagem de voz: a rota /chat/transcricao. O Gemini é trocado por um falso (nenhuma chamada externa)."""

import pytest
from fastapi.testclient import TestClient

from agent.transcription import SemFala
from api.dependencies import modelo_do_assistente
from api.main import app
from api.routes import assistant as rota
from api.tests.fakes import USUARIO

AUDIO = b"\x1aE\xdf\xa3" + b"0" * 2000  # bytes quaisquer: a transcrição é falsa


@pytest.fixture
def transcricoes(monkeypatch):
    feitas = []

    def transcreve_falso(modelo, audio, mime_type):
        feitas.append({"bytes": len(audio), "mime_type": mime_type})
        return "quanto gastei de mercado?"

    app.dependency_overrides[modelo_do_assistente] = lambda: object()
    monkeypatch.setattr(rota, "transcreve", transcreve_falso)
    return feitas


def _envia(conteudo=AUDIO, tipo="audio/webm;codecs=opus"):
    return TestClient(app).post("/api/chat/transcricao", files={"audio": ("voz.webm", conteudo, tipo)})


def test_transcreve_e_nao_grava_nada(db, transcricoes):
    r = _envia()
    assert r.status_code == 200 and r.json() == {"texto": "quanto gastei de mercado?"}
    # o codec sai do tipo: o Gemini recebe só "audio/webm"
    assert transcricoes == [{"bytes": len(AUDIO), "mime_type": "audio/webm"}]
    assert db.lista_conversas(USUARIO.id) == []  # transcrever não cria conversa nem mensagem


def test_aceita_o_audio_do_iphone(transcricoes):
    assert _envia(tipo="audio/mp4").status_code == 200
    assert transcricoes[-1]["mime_type"] == "audio/mp4"


def test_recusa_o_que_nao_e_audio(transcricoes):
    r = _envia(b"%PDF-1.7", "application/pdf")
    assert r.status_code == 415 and transcricoes == []


def test_recusa_audio_grande_demais(transcricoes):
    r = _envia(b"0" * (rota.TAMANHO_MAXIMO_AUDIO + 1))
    assert r.status_code == 413 and transcricoes == []


def test_recusa_gravacao_vazia(transcricoes):
    assert _envia(b"").status_code == 400 and transcricoes == []


def test_sem_fala_no_audio(monkeypatch, transcricoes):
    def sem_fala(*_):
        raise SemFala

    monkeypatch.setattr(rota, "transcreve", sem_fala)
    r = _envia()
    assert r.status_code == 422 and "fala" in r.json()["detail"]


def test_falha_do_gemini_vira_502(monkeypatch, transcricoes):
    def falha(*_):
        raise RuntimeError("503 high demand")

    monkeypatch.setattr(rota, "transcreve", falha)
    assert _envia().status_code == 502


def test_limite_de_mensagens_de_voz(transcricoes):
    for _ in range(10):
        assert _envia().status_code == 200
    assert _envia().status_code == 429
