"""Cifra o texto original das transações (sem anonimizar) antes de ir para o banco.

O banco só guarda o texto cifrado (Fernet: AES-128-CBC + HMAC-SHA256). A chave fica no .env
(CHAVE_ORIGINAIS), nunca no banco: quem abrir o Supabase vê texto embaralhado. A API decifra só
para mostrar ao dono da transação; o ML, o chat (Gemini) e o treino usam só o texto anonimizado.

    python -m api.cifra --nova-chave     gera uma chave para o .env
"""

from __future__ import annotations

import json
import logging
import sys

from cryptography.fernet import Fernet, InvalidToken

from . import config

log = logging.getLogger(__name__)


class ChaveInvalida(Exception):
    """CHAVE_ORIGINAIS está preenchida, mas não é uma chave Fernet válida."""


def _fernet() -> Fernet | None:
    if not config.CHAVE_ORIGINAIS:
        return None
    try:
        return Fernet(config.CHAVE_ORIGINAIS.encode())
    except ValueError:
        raise ChaveInvalida("CHAVE_ORIGINAIS inválida no .env: gere com python -m api.cifra --nova-chave") from None


def ativa() -> bool:
    """Há chave configurada? Sem ela, os originais não são gravados."""
    return _fernet() is not None


def cifra(original: dict[str, str]) -> str | None:
    """{"historico", "contraparte"} -> texto cifrado; None se não houver chave."""
    f = _fernet()
    if f is None:
        return None
    return f.encrypt(json.dumps(original, ensure_ascii=False).encode()).decode()


def decifra(cifrado: str | None) -> dict[str, str] | None:
    """Texto cifrado -> {"historico", "contraparte"}; None se vazio, sem chave ou chave diferente."""
    if not cifrado:
        return None
    f = _fernet()
    if f is None:
        return None
    try:
        return json.loads(f.decrypt(cifrado.encode()))
    except (InvalidToken, ValueError):
        # cifrado com outra chave (ex.: outra máquina com chave diferente): mostra o anonimizado
        log.warning("texto original não pôde ser decifrado (chave diferente?)")
        return None


if __name__ == "__main__":
    if sys.argv[1:] == ["--nova-chave"]:
        print(Fernet.generate_key().decode())
    else:
        print(__doc__)
