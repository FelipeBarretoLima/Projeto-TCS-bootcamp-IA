"""Text and amount normalization (no bank business rules at all)."""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation

_SPACES = re.compile(r"\s+")
_PUNCTUATION_ONLY = re.compile(r"^[^\w]+$")
_HAS_DIGIT = re.compile(r"\d")


def normalize_text(text: str) -> str:
    """Uppercase, Unicode NFC and single spaces. Keeps accents and punctuation."""
    text = unicodedata.normalize("NFC", text).upper()
    return _SPACES.sub(" ", text).strip()


def normalize_history(text: str) -> str:
    """Canonical form of the history.

    Besides `normalize_text`, drops tokens with digits (document no., installment,
    code) and punctuation-only tokens left loose (e.g. the "-" in "TED - 123").
    """
    tokens = [
        t for t in normalize_text(text).split(" ")
        if t and not _HAS_DIGIT.search(t) and not _PUNCTUATION_ONLY.match(t)
    ]
    return " ".join(tokens)


def strip_accents(text: str) -> str:
    """Removes accents (only for internal comparisons; never for the output)."""
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


_BR_AMOUNT = re.compile(r"^(?P<sinal_ini>[-+])?\s*(?:R\$)?\s*(?P<sinal_meio>[-+])?\s*"
                       r"(?P<num>\d{1,3}(?:\.\d{3})*|\d+),(?P<cent>\d{2})\s*(?P<sinal_fim>[-+])?$")


def br_amount(text: str) -> Decimal:
    """Converts an amount in Brazilian format to Decimal.

    Accepts "1.234,56", "R$ 1.234,56", "-R$ 1,00", "R$ -1,00" and "1.234,56-".
    Any other form raises ValueError: the parser must handle its own suffixes
    (e.g. Sicoob's C/D) before calling this function.
    """
    m = _BR_AMOUNT.match(text.strip())
    if not m:
        raise ValueError("valor em formato não reconhecido")
    signs = [s for s in (m["sinal_ini"], m["sinal_meio"], m["sinal_fim"]) if s]
    if len(signs) > 1:
        raise ValueError("valor com mais de um sinal")
    try:
        valor = Decimal(f"{m['num'].replace('.', '')}.{m['cent']}")
    except InvalidOperation as exc:  # pragma: no cover - the regex already guarantees digits
        raise ValueError("valor inválido") from exc
    return -valor if signs == ["-"] else valor
