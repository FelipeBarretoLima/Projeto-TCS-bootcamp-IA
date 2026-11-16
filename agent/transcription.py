"""Chat voice message: Gemini turns the audio into text.

The audio only passes through here (it goes to Gemini and is discarded); what gets saved is the
question in text, after the user checks it and sends it through the normal chat. It uses the same
models as the assistant (primary + fallbacks), tried in order if one fails.

The instruction sent to Gemini stays in Portuguese, like the assistant prompt.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage

from .assistant import Models

NO_SPEECH = "[sem fala]"

INSTRUCTION = (
    "Transcreva fielmente a fala deste áudio, em português do Brasil. "
    "Responda somente com o texto falado: sem comentários, sem aspas e sem responder ao que foi dito. "
    "Escreva números e valores como algarismos (ex.: 'R$ 50', '3 meses'). "
    f"Se não houver nenhuma fala compreensível, responda exatamente {NO_SPEECH}"
)


class NoSpeech(Exception):
    """The audio has no speech that can be transcribed (silence, noise...)."""


def _text(output) -> str:
    text = output.text if hasattr(output, "text") else str(output.content)
    return text.strip().strip('"“”').strip()


def transcribe(model, audio: bytes, mime_type: str) -> str:
    """Text spoken in the audio. `model`: a LangChain chat model or `Models` (primary + fallbacks).

    NoSpeech if there is no speech; the last Gemini exception if every model fails."""
    primary, fallbacks = (model.primary, model.fallbacks) if isinstance(model, Models) else (model, ())
    message = HumanMessage(content=[
        {"type": "text", "text": INSTRUCTION},
        {"type": "media", "data": audio, "mime_type": mime_type},
    ])
    last_error: Exception | None = None
    for candidate in (primary, *fallbacks):
        try:
            text = _text(candidate.invoke([message]))
        except Exception as error:  # 503, timeout, quota...: tries the next model
            last_error = error
            continue
        if not text or NO_SPEECH in text:
            raise NoSpeech
        return text
    assert last_error is not None
    raise last_error
