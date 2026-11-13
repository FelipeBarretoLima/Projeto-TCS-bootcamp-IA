"""Transcrição da mensagem de voz (sem chamar o Gemini: modelos falsos)."""

import pytest

from agent.assistant import Modelos
from agent.transcription import SEM_FALA, SemFala, transcreve


class Saida:
    def __init__(self, texto):
        self.text = texto


class ModeloFalso:
    def __init__(self, resposta=None, erro=None):
        self.resposta, self.erro, self.mensagens = resposta, erro, []

    def invoke(self, mensagens):
        self.mensagens.append(mensagens)
        if self.erro:
            raise self.erro
        return Saida(self.resposta)


def test_manda_o_audio_ao_modelo_e_devolve_o_texto_limpo():
    modelo = ModeloFalso('  "Quanto gastei de mercado?"  ')
    assert transcreve(modelo, b"audio", "audio/webm") == "Quanto gastei de mercado?"
    partes = modelo.mensagens[0][0].content
    assert partes[1] == {"type": "media", "data": b"audio", "mime_type": "audio/webm"}


def test_tenta_o_reserva_quando_o_principal_falha():
    principal = ModeloFalso(erro=RuntimeError("503"))
    reserva = ModeloFalso("Onde gastei mais?")
    assert transcreve(Modelos(principal, (reserva,)), b"audio", "audio/mp4") == "Onde gastei mais?"


def test_todos_falham_repassa_o_ultimo_erro():
    erro = TimeoutError("demorou")
    with pytest.raises(TimeoutError):
        transcreve(Modelos(ModeloFalso(erro=RuntimeError("503")), (ModeloFalso(erro=erro),)), b"a", "audio/webm")


@pytest.mark.parametrize("resposta", [SEM_FALA, "", "   "])
def test_sem_fala(resposta):
    with pytest.raises(SemFala):
        transcreve(ModeloFalso(resposta), b"audio", "audio/webm")
