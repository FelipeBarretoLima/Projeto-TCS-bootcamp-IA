"""Chooses the parser for a file. Exactly one must recognize it."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from .base import AmbiguousFormat, UnrecognizedFormat, Parser
from .bradesco_cartao_pdf import BradescoCardPdf
from .bradesco_conta_pdf import BradescoAccountPdf
from .inter_conta_pdf import InterAccountPdf
from .nubank_conta_csv import NubankAccountCsv
from .nubank_conta_pdf import NubankAccountPdf
from .nubank_fatura_pdf import NubankInvoicePdf
from .santander_cartao_pdf import SantanderCardPdf
from .sicoob_conta_pdf import SicoobAccountPdf

# One parser per format in the inventory.
PARSERS: list[type[Parser]] = [
    BradescoCardPdf,
    BradescoAccountPdf,
    InterAccountPdf,
    NubankAccountCsv,
    NubankAccountPdf,
    NubankInvoicePdf,
    SantanderCardPdf,
    SicoobAccountPdf,
]


def choose_parser(path: Path, parsers: Sequence[type[Parser]] | None = None) -> Parser:
    candidates = PARSERS if parsers is None else parsers
    recognizers = [p for p in candidates if p.detect(path)]
    if not recognizers:
        raise UnrecognizedFormat("nenhum parser reconhece o arquivo")
    if len(recognizers) > 1:
        names = ", ".join(sorted(p.name for p in recognizers))
        raise AmbiguousFormat(f"mais de um parser reconhece o arquivo: {names}")
    return recognizers[0]()
