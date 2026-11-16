"""Voice message: the /chat/transcricao route. Gemini is replaced by a fake (no external call)."""

import pytest
from fastapi.testclient import TestClient

from agent.transcription import NoSpeech
from api.dependencies import assistant_model
from api.main import app
from api.routes import assistant as route
from api.tests.fakes import USER

AUDIO = b"\x1aE\xdf\xa3" + b"0" * 2000  # any bytes: the transcription is fake


@pytest.fixture
def transcriptions(monkeypatch):
    made = []

    def fake_transcribe(model, audio, mime_type):
        made.append({"bytes": len(audio), "mime_type": mime_type})
        return "quanto gastei de mercado?"

    app.dependency_overrides[assistant_model] = lambda: object()
    monkeypatch.setattr(route, "transcribe", fake_transcribe)
    return made


def _send(content=AUDIO, kind="audio/webm;codecs=opus"):
    return TestClient(app).post("/api/chat/transcricao", files={"audio": ("voz.webm", content, kind)})


def test_transcribes_and_saves_nothing(db, transcriptions):
    r = _send()
    assert r.status_code == 200 and r.json() == {"texto": "quanto gastei de mercado?"}
    # the codec is dropped from the type: Gemini receives only "audio/webm"
    assert transcriptions == [{"bytes": len(AUDIO), "mime_type": "audio/webm"}]
    assert db.list_conversations(USER.id) == []  # transcribing creates no conversation nor message


def test_accepts_the_iphone_audio(transcriptions):
    assert _send(kind="audio/mp4").status_code == 200
    assert transcriptions[-1]["mime_type"] == "audio/mp4"


def test_refuses_what_is_not_audio(transcriptions):
    r = _send(b"%PDF-1.7", "application/pdf")
    assert r.status_code == 415 and transcriptions == []


def test_refuses_audio_too_large(transcriptions):
    r = _send(b"0" * (route.MAX_AUDIO_SIZE + 1))
    assert r.status_code == 413 and transcriptions == []


def test_refuses_empty_recording(transcriptions):
    assert _send(b"").status_code == 400 and transcriptions == []


def test_no_speech_in_the_audio(monkeypatch, transcriptions):
    def no_speech(*_):
        raise NoSpeech

    monkeypatch.setattr(route, "transcribe", no_speech)
    r = _send()
    assert r.status_code == 422 and "fala" in r.json()["detail"]


def test_gemini_failure_becomes_502(monkeypatch, transcriptions):
    def fails(*_):
        raise RuntimeError("503 high demand")

    monkeypatch.setattr(route, "transcribe", fails)
    assert _send().status_code == 502


def test_voice_message_limit(transcriptions):
    for _ in range(10):
        assert _send().status_code == 200
    assert _send().status_code == 429
