"""Normalização de texto e de valores (sem regra de negócio de banco nenhum)."""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation

_ESPACOS = re.compile(r"\s+")
_SO_PONTUACAO = re.compile(r"^[^\w]+$")
_TEM_DIGITO = re.compile(r"\d")


def normaliza_texto(texto: str) -> str:
    """Maiúsculas, Unicode NFC e espaços simples. Mantém acentos e pontuação."""
    texto = unicodedata.normalize("NFC", texto).upper()
    return _ESPACOS.sub(" ", texto).strip()


def normaliza_historico(texto: str) -> str:
    """Forma canônica do histórico.

    Além de `normaliza_texto`, descarta tokens com dígito (nº de documento, parcela,
    código) e tokens só de pontuação que sobram soltos (ex.: o "-" de "TED - 123").
    """
    tokens = [
        t for t in normaliza_texto(texto).split(" ")
        if t and not _TEM_DIGITO.search(t) and not _SO_PONTUACAO.match(t)
    ]
    return " ".join(tokens)


def sem_acento(texto: str) -> str:
    """Remove acentos (só para comparações internas; nunca para a saída)."""
    decomposto = unicodedata.normalize("NFD", texto)
    return "".join(c for c in decomposto if unicodedata.category(c) != "Mn")


_VALOR_BR = re.compile(r"^(?P<sinal_ini>[-+])?\s*(?:R\$)?\s*(?P<sinal_meio>[-+])?\s*"
                       r"(?P<num>\d{1,3}(?:\.\d{3})*|\d+),(?P<cent>\d{2})\s*(?P<sinal_fim>[-+])?$")


def valor_br(texto: str) -> Decimal:
    """Converte valor no formato brasileiro para Decimal.

    Aceita "1.234,56", "R$ 1.234,56", "-R$ 1,00", "R$ -1,00" e "1.234,56-".
    Qualquer outra forma gera ValueError: o parser deve tratar sufixos próprios
    (ex.: C/D do Sicoob) antes de chamar esta função.
    """
    m = _VALOR_BR.match(texto.strip())
    if not m:
        raise ValueError("valor em formato não reconhecido")
    sinais = [s for s in (m["sinal_ini"], m["sinal_meio"], m["sinal_fim"]) if s]
    if len(sinais) > 1:
        raise ValueError("valor com mais de um sinal")
    try:
        valor = Decimal(f"{m['num'].replace('.', '')}.{m['cent']}")
    except InvalidOperation as exc:  # pragma: no cover - regex já garante dígitos
        raise ValueError("valor inválido") from exc
    return -valor if sinais == ["-"] else valor
