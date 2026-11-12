"""Splits the city off the end of a merchant name (official IBGE list of municipalities).

Card invoices and statements show "MERCHANT CITY" with collapsed spaces,
with no fixed position. The city is recognized by dictionary, not by heuristic:
the longest token suffix that is a municipality (or the start of one, when the card
network's city field was truncated at a fixed width).
"""

from __future__ import annotations

import re
from functools import lru_cache
from importlib.resources import files

from .normalization import strip_accents

_MAX_TOKENS = 6  # "SAO JOSE DO VALE DO RIO PRETO" has 7, but truncated it fits in fewer


def key(text: str) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", strip_accents(text).upper()).strip()


@lru_cache(maxsize=1)
def municipalities() -> frozenset[str]:
    text = files("statement").joinpath("dados/municipios.txt").read_text("utf-8")
    return frozenset(l for l in text.splitlines() if l and not l.startswith("#"))


@lru_cache(maxsize=8)
def _truncated(width: int) -> frozenset[str]:
    """How the municipality appears in a fixed-width field (the trailing space disappears)."""
    return frozenset(m[:width].rstrip() for m in municipalities() if len(m) > width)


def split_city(text: str, truncated_width: int | None = None) -> tuple[str, str] | None:
    """(merchant, city) or None if the end of the text is not a municipality.

    truncated_width: width of the city field when the layout truncates it (e.g. 13).
    In that case it also accepts the municipality cut at that width ("SAO JOSE DOS").
    At least one token is always left for the merchant.
    """
    tokens = text.split()
    for k in range(min(_MAX_TOKENS, len(tokens) - 1), 0, -1):
        candidate = key(" ".join(tokens[-k:]))
        exact = candidate in municipalities()
        truncated = truncated_width is not None and candidate in _truncated(truncated_width)
        if exact or truncated:
            return " ".join(tokens[:-k]), candidate
    return None
