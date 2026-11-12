"""Checks the extracted transactions against the totals declared in the document."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from decimal import Decimal

from .parsers.base import ExtractionError, ExtractionResult


class ReconciliationFailed(ExtractionError):
    code = "ReconciliacaoFalhou"  # stable code: goes to the report/API
    def __init__(self, divergent: int, total: int, motivo: str = "soma não bate com o total declarado"):
        super().__init__(f"{motivo}: {divergent} de {total} segmento(s)")
        self.divergent = divergent
        self.total = total


@dataclass(frozen=True)
class ReconciliationStatus:
    segmentos: int
    divergent: int

    @property
    def ok(self) -> bool:
        return self.segmentos > 0 and self.divergent == 0


def check(result: ExtractionResult) -> ReconciliationStatus:
    """Computes the status without raising."""
    running_sum: dict[int, Decimal] = defaultdict(Decimal)
    for t in result.transactions:
        for idx in (t.segment if isinstance(t.segment, tuple) else (t.segment,)):
            running_sum[idx] += t.valor
    n = len(result.segmentos)
    orphans = sum(1 for idx in running_sum if not 0 <= idx < n)
    divergent = orphans + sum(
        1 for i, s in enumerate(result.segmentos) if s.opening + running_sum[i] != s.closing
    )
    return ReconciliationStatus(segmentos=n, divergent=divergent)


def _indices(t) -> tuple[int, ...]:
    return t.segment if isinstance(t.segment, tuple) else (t.segment,)


def split_divergent_documents(result: ExtractionResult) -> tuple[ExtractionResult, list[str]]:
    """For files with several independent documents (REJECT_BY_DOCUMENT).

    Returns (result with only the documents that balance, rejected documents). Requires every
    segment to have `documento` and no entry to mix documents.
    """
    n = len(result.segmentos)
    if not n or any(not s.document for s in result.segmentos):
        raise ReconciliationFailed(0, n, "segmento sem documento")
    running_sum: dict[int, Decimal] = defaultdict(Decimal)
    for t in result.transactions:
        idx = _indices(t)
        if any(not 0 <= i < n for i in idx) or len({result.segmentos[i].document for i in idx}) > 1:
            raise ReconciliationFailed(1, n, "lançamento fora de segmento ou em dois documentos")
        for i in idx:
            running_sum[i] += t.valor
    bad = sorted({s.document for i, s in enumerate(result.segmentos) if s.opening + running_sum[i] != s.closing})
    if not bad:
        return result, []
    keeps = lambda t: not any(result.segmentos[i].document in bad for i in _indices(t))
    name_map = {i: j for j, i in enumerate(i for i, s in enumerate(result.segmentos) if s.document not in bad)}
    segmentos = [s for s in result.segmentos if s.document not in bad]
    transactions = []
    for t in result.transactions:
        if keeps(t):
            transactions.append(replace(t, segment=tuple(name_map[i] for i in _indices(t))))
    return replace(result, transactions=transactions, segmentos=segmentos), bad


def reconcile(result: ExtractionResult) -> ReconciliationStatus:
    """Like `check`, but rejects the file if something does not match."""
    if not result.segmentos:
        raise ReconciliationFailed(0, 0, "documento sem totais declarados")
    status = check(result)
    if not status.ok:
        raise ReconciliationFailed(status.divergent, status.segmentos)
    return status
