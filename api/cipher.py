"""Cifra o texto original das transações (sem anonimizar) antes de ir para o banco.

O banco só guarda o texto cifrado (Fernet: AES-128-CBC + HMAC-SHA256). A chave fica no .env
(CHAVE_ORIGINAIS), nunca no banco: quem abrir o Supabase vê texto embaralhado. A API decifra só
para mostrar ao dono da transação; o ML, o chat (Gemini) e o treino usam só o texto anonimizado.

    python -m api.cipher --nova-chave     gera uma chave para o .env
"""

# The module docstring above is the CLI help (printed by `python -m api.cipher`), so it stays in Portuguese.

from __future__ import annotations

import json
import logging
import sys

from cryptography.fernet import Fernet, InvalidToken

from . import config

log = logging.getLogger(__name__)


class InvalidKey(Exception):
    """CHAVE_ORIGINAIS is filled in, but it is not a valid Fernet key."""


def _fernet() -> Fernet | None:
    if not config.ORIGINALS_KEY:
        return None
    try:
        return Fernet(config.ORIGINALS_KEY.encode())
    except ValueError:
        raise InvalidKey("CHAVE_ORIGINAIS inválida no .env: gere com python -m api.cipher --nova-chave") from None


def enabled() -> bool:
    """Is a key configured? Without it, the originals are not saved."""
    return _fernet() is not None


def encrypt(original: dict[str, str]) -> str | None:
    """{"historico", "contraparte"} -> encrypted text; None if there is no key."""
    f = _fernet()
    if f is None:
        return None
    return f.encrypt(json.dumps(original, ensure_ascii=False).encode()).decode()


def decrypt(encrypted: str | None) -> dict[str, str] | None:
    """Encrypted text -> {"historico", "contraparte"}; None if empty, without a key or with a different key."""
    if not encrypted:
        return None
    f = _fernet()
    if f is None:
        return None
    try:
        return json.loads(f.decrypt(encrypted.encode()))
    except (InvalidToken, ValueError):
        # encrypted with another key (e.g. another machine with a different key): show the anonymized text
        log.warning("texto original não pôde ser decifrado (chave diferente?)")
        return None


if __name__ == "__main__":
    if sys.argv[1:] == ["--nova-chave"]:
        print(Fernet.generate_key().decode())
    else:
        print(__doc__)
