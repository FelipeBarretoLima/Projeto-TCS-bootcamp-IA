"""Voice message transcription (without calling Gemini: fake models)."""

import pytest

from agent.assistant import Models
from agent.transcription import NO_SPEECH, NoSpeech, transcribe


class Output:
    def __init__(self, text):
        self.text = text


class FakeModel:
    def __init__(self, answer=None, error=None):
        self.answer, self.error, self.messages = answer, error, []

    def invoke(self, messages):
        self.messages.append(messages)
        if self.error:
            raise self.error
        return Output(self.answer)


def test_sends_the_audio_to_the_model_and_returns_the_clean_text():
    model = FakeModel('  "Quanto gastei de mercado?"  ')
    assert transcribe(model, b"audio", "audio/webm") == "Quanto gastei de mercado?"
    parts = model.messages[0][0].content
    assert parts[1] == {"type": "media", "data": b"audio", "mime_type": "audio/webm"}


def test_tries_the_fallback_when_the_primary_fails():
    primary = FakeModel(error=RuntimeError("503"))
    fallback = FakeModel("Onde gastei mais?")
    assert transcribe(Models(primary, (fallback,)), b"audio", "audio/mp4") == "Onde gastei mais?"


def test_all_fail_raises_the_last_error():
    error = TimeoutError("demorou")
    with pytest.raises(TimeoutError):
        transcribe(Models(FakeModel(error=RuntimeError("503")), (FakeModel(error=error),)), b"a", "audio/webm")


@pytest.mark.parametrize("answer", [NO_SPEECH, "", "   "])
def test_no_speech(answer):
    with pytest.raises(NoSpeech):
        transcribe(FakeModel(answer), b"audio", "audio/webm")
