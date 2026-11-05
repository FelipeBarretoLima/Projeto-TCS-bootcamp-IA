"""Escolhe o parser de um arquivo. Exatamente um tem que reconhecer."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from .base import FormatoAmbiguo, FormatoNaoReconhecido, Parser
from .bradesco_cartao_pdf import BradescoCartaoPdf
from .bradesco_conta_pdf import BradescoContaPdf
from .inter_conta_pdf import InterContaPdf
from .nubank_conta_csv import NubankContaCsv
from .nubank_conta_pdf import NubankContaPdf
from .nubank_fatura_pdf import NubankFaturaPdf
from .santander_cartao_pdf import SantanderCartaoPdf
from .sicoob_conta_pdf import SicoobContaPdf

# Um parser por formato do inventário.
PARSERS: list[type[Parser]] = [
    BradescoCartaoPdf,
    BradescoContaPdf,
    InterContaPdf,
    NubankContaCsv,
    NubankContaPdf,
    NubankFaturaPdf,
    SantanderCartaoPdf,
    SicoobContaPdf,
]


def escolhe_parser(caminho: Path, parsers: Sequence[type[Parser]] | None = None) -> Parser:
    candidatos = PARSERS if parsers is None else parsers
    reconhecem = [p for p in candidatos if p.detecta(caminho)]
    if not reconhecem:
        raise FormatoNaoReconhecido("nenhum parser reconhece o arquivo")
    if len(reconhecem) > 1:
        nomes = ", ".join(sorted(p.nome for p in reconhecem))
        raise FormatoAmbiguo(f"mais de um parser reconhece o arquivo: {nomes}")
    return reconhecem[0]()
