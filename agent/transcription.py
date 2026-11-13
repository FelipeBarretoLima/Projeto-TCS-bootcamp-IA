"""Mensagem de voz do chat: o Gemini transforma o áudio em texto.

O áudio só passa por aqui (vai ao Gemini e é descartado); o que fica salvo é a pergunta em texto,
depois que o usuário confere e envia pelo chat normal. Usa os mesmos modelos do assistente
(principal + reservas), tentados em ordem se um falhar.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage

from .assistant import Modelos

SEM_FALA = "[sem fala]"

INSTRUCAO = (
    "Transcreva fielmente a fala deste áudio, em português do Brasil. "
    "Responda somente com o texto falado: sem comentários, sem aspas e sem responder ao que foi dito. "
    "Escreva números e valores como algarismos (ex.: 'R$ 50', '3 meses'). "
    f"Se não houver nenhuma fala compreensível, responda exatamente {SEM_FALA}"
)


class SemFala(Exception):
    """O áudio não tem fala que dê para transcrever (silêncio, ruído...)."""


def _texto(saida) -> str:
    texto = saida.text if hasattr(saida, "text") else str(saida.content)
    return texto.strip().strip('"“”').strip()


def transcreve(modelo, audio: bytes, mime_type: str) -> str:
    """Texto falado no áudio. `modelo`: um chat model do LangChain ou `Modelos` (principal + reservas).

    SemFala se não houver fala; a última exceção do Gemini se todos os modelos falharem."""
    principal, reservas = (modelo.principal, modelo.reservas) if isinstance(modelo, Modelos) else (modelo, ())
    mensagem = HumanMessage(content=[
        {"type": "text", "text": INSTRUCAO},
        {"type": "media", "data": audio, "mime_type": mime_type},
    ])
    ultimo_erro: Exception | None = None
    for candidato in (principal, *reservas):
        try:
            texto = _texto(candidato.invoke([mensagem]))
        except Exception as erro:  # 503, demora, cota...: tenta o próximo modelo
            ultimo_erro = erro
            continue
        if not texto or SEM_FALA in texto:
            raise SemFala
        return texto
    assert ultimo_erro is not None
    raise ultimo_erro
