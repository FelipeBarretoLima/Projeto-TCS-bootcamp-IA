"""Personal data patterns, shared by the anonymization and the validator.

All patterns run on text already in uppercase (see `normalize_text`).
`X`, `*` and `•` are treated as mask characters used by the banks.
"""

from __future__ import annotations

import re

from .normalization import normalize_text, strip_accents

_M = r"[\d*•X]"  # digit or mask

# Order matters for removal: longer patterns first, so a short one does not
# cut a piece of another (e.g. a CNPJ inside a bank slip line).
PATTERNS: dict[str, re.Pattern[str]] = {
    # bank slip line (47/48 digits) or barcode (44)
    "boleto": re.compile(r"\d(?:[\s.]?\d){43,47}"),
    "email": re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),
    # UUID: format of random PIX keys
    "chave_pix_aleatoria": re.compile(
        r"\b[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}\b"
    ),
    "cnpj": re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}\s?/?\s?\d{4}-?\d{2}\b"),  # the slash sometimes becomes a space
    # full or masked CPF (•••.123.456-••, ***.123.456-**)
    "cpf": re.compile(rf"(?<![\w*•]){_M}{{3}}\.\s?{_M}{{3}}\.\s?{_M}{{3}}\s?-\s?{_M}{{2}}(?![\w*•])"),
    "cartao": re.compile(
        r"(?<![\w*•])\d{4}(?:[\s.-]?[\d*•X]{4}){2}[\s.-]?\d{4}\b"  # 16 positions, full or masked
        r"|(?<![A-Z])(?:[*•X]{2,}[\s.-]*)+\d{4}\b"  # **** 1234 / XXXX.1234
        r"|\b\d{4}[\s.-]*[*•X]{2,}(?![A-Z])"  # 1234 ****
        r"|\bFINAL\s*:?\s*\d{4}\b"  # "FINAL 1234"
        r"|\bCART[ÃA]O\s*(?:N[º°O.]?\s*)?:?\s*\d{4}\b"  # "CARTÃO 1234"
    ),
    "agencia_conta": re.compile(
        r"\bAG(?:[ÊE]NCIA|\.)?\s*:?\s*\d[\d-]*"
        r"|\b(?:CONTA|C/C|CC)\s*(?:CORRENTE\s*)?(?:N[º°O.]?\s*)?:?\s*\d[\d.-]*"
    ),
    "telefone": re.compile(r"(?:\+?55\s?)?(?:\(\d{2}\)|\b\d{2})\s?9?\d{4}[\s-]?\d{4}\b"),
    "cep": re.compile(r"\b\d{5}-?\d{3}\b"),
    "endereco": re.compile(
        r"\b(?:RUA|R\.|AV\.?|AVENIDA|TRAVESSA|TV\.|ALAMEDA|AL\.|RODOVIA|ROD\.|ESTRADA|PRA[ÇC]A|LARGO)"
        r"\s+[^\d,;]{2,}?,?\s*(?:N[º°O.]?\s*)?\d+"
    ),
    # any sequence of 6+ digits (account, document, code, protocol)
    "codigo_numerico": re.compile(r"\d(?:[.\-/]?\d){5,}"),
}

# Words that identify no one on their own and are not part of name pairs.
_CONNECTIVES = {"DE", "DA", "DO", "DAS", "DOS", "E", "D"}


def name_variants(name: str) -> list[str]:
    """Forms of a name that must not appear in the output.

    Full name + each pair of consecutive tokens (ignoring connectives):
    "MARIA DA SILVA SOUZA" -> "MARIA DA SILVA SOUZA", "MARIA SILVA", "SILVA SOUZA".
    Loose tokens are not included: a surname alone appears in company names
    and would block legitimate rows.
    """
    base = strip_accents(normalize_text(name))
    tokens = [t for t in re.findall(r"[A-Z]+", base) if t not in _CONNECTIVES and len(t) > 1]
    variants = {base} if base else set()
    variants.update(f"{a} {b}" for a, b in zip(tokens, tokens[1:]))
    return sorted(variants, key=len, reverse=True)


def names_regex(names: list[str]) -> re.Pattern[str] | None:
    """Single regex (over accent-free text) for all the name variants."""
    variants: set[str] = set()
    for name in names:
        variants.update(name_variants(name))
    if not variants:
        return None
    parts = []
    for v in sorted(variants, key=len, reverse=True):
        # between tokens it accepts spaces and connectives ("MARIA SILVA" matches "MARIA DA SILVA")
        tokens = [re.escape(t) for t in v.split(" ")]
        parts.append(r"(?:\s+(?:(?:DE|DA|DO|DAS|DOS|E)\s+)*)".join(tokens))
    return re.compile(r"\b(?:" + "|".join(parts) + r")\b")


def _strip_accents_same_length(text: str) -> str:
    """`strip_accents` that preserves positions (NFC text: 1 character -> 1 character)."""
    converted = "".join(strip_accents(c)[:1] or c for c in text)
    assert len(converted) == len(text)
    return converted


def find(text: str, names: re.Pattern[str] | None = None) -> list[str]:
    """Kinds of personal data present in the text (only the kind names, never the excerpt)."""
    text = normalize_text(text)
    found = [tipo for tipo, rx in PATTERNS.items() if rx.search(text)]
    if names is not None and names.search(_strip_accents_same_length(text)):
        found.append("nome_titular")
    return found


def remove(text: str, names: re.Pattern[str] | None = None) -> str:
    """Erases every excerpt that matches some pattern (and the holder names)."""
    text = normalize_text(text)
    for rx in PATTERNS.values():
        text = rx.sub(" ", text)
    if names is not None:
        base = _strip_accents_same_length(text)
        # erase from end to start so positions do not shift
        for m in reversed(list(names.finditer(base))):
            text = text[: m.start()] + " " + text[m.end():]
    return text
