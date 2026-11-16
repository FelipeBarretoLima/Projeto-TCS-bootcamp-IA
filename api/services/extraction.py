"""Bridge between the API and the extraction module (`statement`)."""

import tempfile
from dataclasses import asdict
from pathlib import Path

from statement.merchants import declared_people
from statement.parsers.base import first_line, pdf_text
from statement.pipeline import run

from .. import config
from ..schemas import Report, Transaction, UploadResult


class OutputLeak(Exception):
    """The validator found possible personal data: no row can be returned."""


def process_statement(content: bytes, extension: str, pseudonym: str) -> UploadResult:
    """Runs the pipeline in a temporary directory, deleted at the end. Nothing is saved."""
    people = declared_people(config.PRIVATE_DIR)
    try:
        with tempfile.TemporaryDirectory(prefix="extrato_") as tmp:
            folder = Path(tmp)
            # fixed name: the original name may contain personal data; the parsers only look at the extension
            file = folder / f"extrato{extension}"
            file.write_bytes(content)
            execution = run(
                file, pseudonym, folder / "saida.csv", folder / "privado", people=people
            )
    finally:
        # the read caches keep the file text: do not keep it in memory
        pdf_text.cache_clear()
        first_line.cache_clear()

    if execution.leak is not None:
        raise OutputLeak(str(execution.leak))

    data = asdict(execution.reports[0])
    report = Report(**{name: data[name] for name in Report.model_fields})
    # the original (not anonymized) goes along only to show the owner; ML and database use the anonymized text
    transactions = [
        Transaction(**row.model_dump(exclude={"id_usuario"}),
                    historico_original=original["historico"], contraparte_original=original["contraparte"])
        for row, original in zip(execution.lines, execution.originals, strict=True)
    ]
    return UploadResult(relatorio=report, transacoes=transactions)
