"""Limite de uso por usuário (em memória): protege o Gemini e o processamento de extratos de
cliques repetidos ou scripts. Cada processo da API tem a sua contagem; reinicia junto com ela."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock
from typing import Annotated

from fastapi import Depends, HTTPException

from .auth import Usuario, usuario_atual


class Limite:
    def __init__(self, maximo: int, janela_segundos: float, acao: str):
        self.maximo, self.janela, self.acao = maximo, janela_segundos, acao
        self._usos: defaultdict[str, deque[float]] = defaultdict(deque)
        self._trava = Lock()

    def confere(self, chave: str) -> None:
        """Conta um uso; 429 se a chave já usou o máximo dentro da janela."""
        agora = time.monotonic()
        with self._trava:
            usos = self._usos[chave]
            while usos and usos[0] <= agora - self.janela:
                usos.popleft()
            if len(usos) >= self.maximo:
                espera = int(usos[0] + self.janela - agora) + 1
                raise HTTPException(429, f"muitas {self.acao} seguidas: espere {espera} s e tente de novo")
            usos.append(agora)

    def zera(self) -> None:
        with self._trava:
            self._usos.clear()


LIMITE_CHAT = Limite(10, 60, "perguntas")  # 10 perguntas por minuto
LIMITE_IMPORTACAO = Limite(20, 600, "importações")  # 20 extratos a cada 10 minutos
# separado do chat: uma pergunta por voz gasta uma transcrição + uma pergunta, sem dividir o limite
LIMITE_TRANSCRICAO = Limite(10, 60, "mensagens de voz")  # 10 por minuto


def limita_chat(usuario: Annotated[Usuario, Depends(usuario_atual)]) -> None:
    LIMITE_CHAT.confere(str(usuario.id))


def limita_importacao(usuario: Annotated[Usuario, Depends(usuario_atual)]) -> None:
    LIMITE_IMPORTACAO.confere(str(usuario.id))


def limita_transcricao(usuario: Annotated[Usuario, Depends(usuario_atual)]) -> None:
    LIMITE_TRANSCRICAO.confere(str(usuario.id))
