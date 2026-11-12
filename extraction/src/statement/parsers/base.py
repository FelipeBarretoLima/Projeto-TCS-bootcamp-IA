"""Interface every format parser implements.

Each format (bank + product + extension) has its own deterministic parser.
Nothing here is a generic heuristic: the parser only accepts what it knows and fails on the rest.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import ClassVar, Literal

from ..models import PaymentMethod


class ExtractionError(Exception):
    """Base of the pipeline errors. The message never carries statement content."""
    code = "ErroExtracao"  # stable code: goes to the report/API


class UnrecognizedFormat(ExtractionError):
    code = "FormatoNaoReconhecido"  # stable code: goes to the report/API


class AmbiguousFormat(ExtractionError):
    code = "FormatoAmbiguo"  # stable code: goes to the report/API


class UnexpectedLayout(ExtractionError):
    """Something in the file outside the layout the parser knows. Only code + page."""
    code = "LayoutInesperado"  # stable code: goes to the report/API

    def __init__(self, parser: str, motivo: str, page: int | None = None):
        where = f" (página {page})" if page is not None else ""
        super().__init__(f"parser {parser}: {motivo}{where}")
        self.motivo = motivo
        self.page = page


class UnknownHistory(ExtractionError):
    code = "HistoricoDesconhecido"  # stable code: goes to the report/API

    def __init__(self, parser: str, historico: str):
        # the history stays in the attribute (goes to data/privado), not in the message
        super().__init__(f"parser {parser}: histórico fora do mapa explícito")
        self.parser = parser
        self.historico = historico


@dataclass(frozen=True)
class RawTransaction:
    """Entry as read from the document. Lives only in memory.

    historico: the entry type text (e.g. "PIX ENVIADO"), without the complement.
    contraparte: payee/payer/merchant name, if the layout provides it.
    counterparty_document: counterparty CPF/CNPJ as it appears (masked or not), if any.
    segment: index (or indices) in ExtractionResult.segmentos used in reconciliation.
      A transaction can belong to several: e.g. the day total and the statement balance.
    page: only for error messages (never the content).
    """

    data: date
    historico: str
    valor: Decimal
    segment: int | tuple[int, ...]
    contraparte: str = ""
    counterparty_document: str = ""
    page: int | None = None
    # filled by the parser when it cannot guarantee the anonymization itself
    # (e.g. city not identified in the merchant name): the row goes to review
    review_reason: str = ""
    # copy of an entry the document repeats (e.g. boundary day between merged
    # statements): it enters its stretch's reconciliation, but does not go to the CSV
    duplicate: bool = False
    # entry that is not a new movement of the user (e.g. on the invoice, the invoice payment,
    # which is already in the account statement, and the remaining balance of the previous invoice): it enters
    # reconciliation, but does not go to the CSV
    omitted: bool = False


@dataclass(frozen=True)
class Segment:
    """Stretch of the document with declared totals: opening + sum(amounts) == closing.

    Examples:
      checking account: opening = previous balance, closing = final balance (or day balance);
      invoice: opening = -previous invoice balance (0 if none),
               closing = -invoice total (debt is negative).
    """

    label: str  # no personal data, e.g. "fatura 2025-03" or "dia 2024-01-05"
    opening: Decimal
    closing: Decimal
    # independent document inside the file (e.g. "fatura 2026-08-10" in a PDF with several
    # invoices). Only used by parsers with REJECT_BY_DOCUMENT.
    document: str = ""


@dataclass
class ExtractionResult:
    banco: str
    product: Literal["conta", "cartao"]
    transactions: list[RawTransaction]
    segmentos: list[Segment]
    holder_names: list[str] = field(default_factory=list)  # holder + cardholders/additional cards


class Parser(ABC):
    """Contract of a format parser."""

    name: ClassVar[str]  # e.g. "bradesco_conta_pdf"
    banco: ClassVar[str]  # slug of the output contract
    product: ClassVar[Literal["conta", "cartao"]]
    # Explicit map normalized history -> method. Outside the map = error.
    METHODS: ClassVar[Mapping[str, PaymentMethod]]
    # True only for formats that provably carry no balance/total at all
    # (e.g. CSV exported by Nubank). The file is accepted with reconciliation "sem_totais".
    NO_TOTALS: ClassVar[bool] = False
    # True for files that join independent documents (e.g. several merged invoices):
    # a document that does not balance is rejected alone (its rows are dropped) and the rest goes on.
    # Every segment must have `documento`. User decision on 2026-11-04.
    REJECT_BY_DOCUMENT: ClassVar[bool] = False

    @classmethod
    @abstractmethod
    def detect(cls, path: Path) -> bool:
        """True if the file has this format's signature. Must not raise."""

    @abstractmethod
    def extract(self, path: Path) -> ExtractionResult:
        """Reads the whole file. Anything outside the expected layout is an error."""

    @classmethod
    def method_for(cls, normalized_history: str) -> PaymentMethod:
        try:
            return cls.METHODS[normalized_history]
        except KeyError:
            raise UnknownHistory(cls.name, normalized_history) from None


# --- reading helpers for `detect` (cached: several parsers look at the same file) ---

@lru_cache(maxsize=32)
def pdf_text(path: Path, max_pages: int | None = None) -> tuple[str, ...]:
    """Text of each page (pdfplumber). Empty tuple if the file is not a readable PDF."""
    import pdfplumber

    try:
        with pdfplumber.open(path) as pdf:
            pages = pdf.pages if max_pages is None else pdf.pages[:max_pages]
            return tuple(p.extract_text() or "" for p in pages)
    except Exception:  # noqa: BLE001 - detect() must not fail
        return ()


@lru_cache(maxsize=32)
def first_line(path: Path, encoding: str = "utf-8-sig") -> str:
    """First line of the text file ('' if it cannot be read)."""
    try:
        with open(path, encoding=encoding, newline="") as f:
            return f.readline().rstrip("\r\n")
    except (OSError, UnicodeDecodeError):
        return ""
