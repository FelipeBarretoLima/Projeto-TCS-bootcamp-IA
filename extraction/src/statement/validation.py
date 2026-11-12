"""Last barrier before the disk: no personal data pattern gets into the CSV."""

from __future__ import annotations

import csv
import os
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from pathlib import Path

from . import patterns
from .models import COLUMNS, OutputRow
from .parsers.base import ExtractionError


class LeakDetected(ExtractionError):
    code = "VazamentoDetectado"  # stable code: goes to the report/API
    def __init__(self, counts: Counter[str]):
        summary = ", ".join(f"{tipo}={n}" for tipo, n in sorted(counts.items()))
        super().__init__(f"gravação bloqueada: possível dado pessoal no CSV ({summary})")
        self.counts = counts


def verify(lines: Iterable[OutputRow], names: re.Pattern[str] | None) -> Counter[str]:
    """Counts, per kind, how many rows have some forbidden pattern in the text fields."""
    counts: Counter[str] = Counter()
    for line in lines:
        found: set[str] = set()
        for field_name in (line.historico, line.contraparte):
            found.update(patterns.find(field_name, names))
        counts.update(found)
    return counts


def write_csv(
    lines: Sequence[OutputRow], path: Path, holder_names: Sequence[str]
) -> None:
    """Validates everything and only then writes (UTF-8 without BOM, comma, '\\n').

    Writes to a temporary file and renames it at the end: if something fails, the previous
    CSV (if any) stays intact and nothing partial is left on disk.
    """
    names = patterns.names_regex(list(holder_names))
    counts = verify(lines, names)
    if counts:
        raise LeakDetected(counts)

    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    try:
        with open(temp, "w", encoding="utf-8", newline="") as f:
            csv_writer = csv.writer(f, lineterminator="\n")
            csv_writer.writerow(COLUMNS)
            csv_writer.writerows(line.as_csv_row() for line in lines)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
