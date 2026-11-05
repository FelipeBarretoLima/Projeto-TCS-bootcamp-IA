"""Separa a cidade do fim do nome de estabelecimento (lista oficial de municípios do IBGE).

Faturas e extratos de cartão trazem "ESTABELECIMENTO CIDADE" com os espaços colapsados,
sem posição fixa. A cidade é reconhecida por dicionário, não por heurística:
o maior sufixo de tokens que é um município (ou o começo de um, quando o campo de
cidade da bandeira foi truncado na largura fixa).
"""

from __future__ import annotations

import re
from functools import lru_cache
from importlib.resources import files

from .normalizacao import sem_acento

_MAX_TOKENS = 6  # "SAO JOSE DO VALE DO RIO PRETO" tem 7, mas truncado cabe em menos


def chave(texto: str) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", sem_acento(texto).upper()).strip()


@lru_cache(maxsize=1)
def municipios() -> frozenset[str]:
    texto = files("extrato").joinpath("dados/municipios.txt").read_text("utf-8")
    return frozenset(l for l in texto.splitlines() if l and not l.startswith("#"))


@lru_cache(maxsize=8)
def _truncados(largura: int) -> frozenset[str]:
    """Como o município aparece num campo de largura fixa (o espaço final some)."""
    return frozenset(m[:largura].rstrip() for m in municipios() if len(m) > largura)


def separa_cidade(texto: str, largura_truncada: int | None = None) -> tuple[str, str] | None:
    """(estabelecimento, cidade) ou None se o fim do texto não for um município.

    largura_truncada: largura do campo de cidade quando o layout trunca (ex.: 13).
    Nesse caso também aceita o município cortado nessa largura ("SAO JOSE DOS").
    Sempre sobra pelo menos um token para o estabelecimento.
    """
    tokens = texto.split()
    for k in range(min(_MAX_TOKENS, len(tokens) - 1), 0, -1):
        candidato = chave(" ".join(tokens[-k:]))
        exato = candidato in municipios()
        truncado = largura_truncada is not None and candidato in _truncados(largura_truncada)
        if exato or truncado:
            return " ".join(tokens[:-k]), candidato
    return None
