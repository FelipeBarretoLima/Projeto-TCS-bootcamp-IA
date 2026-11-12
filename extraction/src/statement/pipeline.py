"""file -> parser -> reconciliation -> normalization -> anonymization -> validation -> CSV."""

from __future__ import annotations

import csv
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from pydantic import ValidationError

from . import merchants, patterns
from .anonymization import Review, resolve_counterparty
from .models import OutputRow, TransactionType
from .normalization import normalize_history
from .parsers.base import (
    ExtractionError, UnknownHistory, UnexpectedLayout, Parser, ExtractionResult,
)
from .parsers.registry import choose_parser
from .reconciliation import check, reconcile, split_divergent_documents
from .validation import LeakDetected, write_csv

ACCEPTED, REJECTED = "aceito", "rejeitado"


@dataclass
class FileReport:
    """One row of the report. Only counts and codes: nothing from the statement content."""

    arquivo: str
    parser: str = ""
    periodo_inicio: str = ""
    periodo_fim: str = ""
    linhas_extraidas: int = 0
    linhas_gravadas: int = 0
    linhas_revisar: int = 0
    linhas_duplicadas: int = 0
    linhas_omitidas: int = 0
    documentos_rejeitados: int = 0
    historicos_desconhecidos: int = 0
    segmentos: int = 0
    segmentos_divergentes: int = 0
    reconciliacao: str = "nao_executada"
    status: str = REJECTED
    motivo: str = ""


@dataclass
class _Extracted:
    path: Path
    report: FileReport
    parser: Parser | None = None
    result: ExtractionResult | None = None


@dataclass
class Execution:
    reports: list[FileReport]
    lines: list[OutputRow] = field(default_factory=list)
    # ORIGINAL text (not anonymized) of each row, in the same order as `lines`: {"historico", "contraparte"}.
    # Never goes to the CSV or to training; the API only stores it encrypted, to show to the owner.
    originals: list[dict[str, str]] = field(default_factory=list)
    to_review: list[dict[str, str]] = field(default_factory=list)
    unknown: list[dict[str, str]] = field(default_factory=list)
    holder_names: list[str] = field(default_factory=list)
    leak: LeakDetected | None = None

    @property
    def exit_code(self) -> int:
        if self.leak is not None:
            return 2
        return 0 if all(r.status == ACCEPTED for r in self.reports) else 1


def _files(source: Path) -> list[Path]:
    if source.is_file():
        return [source]
    return sorted(
        p for p in source.rglob("*")
        if p.is_file() and not any(part.startswith(".") for part in p.relative_to(source).parts)
    )


def _extract(path: Path, label: str, parsers: Sequence[type[Parser]] | None) -> _Extracted:
    item = _Extracted(path, FileReport(arquivo=label))
    rel = item.report
    try:
        parser = choose_parser(path, parsers)
        rel.parser = parser.name
        result = parser.extract(path)
    except UnexpectedLayout as exc:
        rel.motivo = f"{exc.code}:{exc.motivo}" + (f"@p{exc.page}" if exc.page else "")
        return item
    except ExtractionError as exc:
        rel.motivo = exc.code
        return item
    except Exception as exc:  # noqa: BLE001 - the exception message may contain content
        rel.motivo = f"erro_no_parser:{getattr(exc, 'code', type(exc).__name__)}"
        return item

    rel.linhas_extraidas = len(result.transactions)
    if result.transactions:
        dates = sorted(t.data for t in result.transactions)
        rel.periodo_inicio, rel.periodo_fim = dates[0].isoformat(), dates[-1].isoformat()
    if parser.NO_TOTALS:
        if result.segmentos:
            rel.motivo = "segmentos_em_formato_sem_totais"
            return item
        rel.reconciliacao = "sem_totais"
        item.parser, item.result = parser, result
        return item
    status = check(result)
    rel.segmentos, rel.segmentos_divergentes = status.segmentos, status.divergent
    rejected: list[str] = []
    try:
        if parser.REJECT_BY_DOCUMENT:
            result, rejected = split_divergent_documents(result)
        reconcile(result)
    except ExtractionError as exc:
        rel.reconciliacao, rel.motivo = "falhou", exc.code
        return item
    rel.reconciliacao = "ok"
    if rejected:
        # document labels are only type + date (e.g. "fatura 2026-08-10"): no personal data
        rel.reconciliacao = "ok_com_documentos_rejeitados"
        rel.documentos_rejeitados = len(rejected)
        rel.motivo = "documentos_rejeitados:" + ";".join(rejected)
    item.parser, item.result = parser, result
    return item


def _transform(item: _Extracted, user: str, names: re.Pattern[str] | None, execution: Execution,
                people: frozenset[str] = frozenset()) -> None:
    assert item.parser is not None and item.result is not None
    rel, parser, result = item.report, item.parser, item.result
    lines: list[OutputRow] = []
    originals: list[dict[str, str]] = []
    to_review: list[dict[str, str]] = []
    unknown: set[str] = set()
    invalid = 0

    duplicate_rows = sum(t.duplicate for t in result.transactions)
    omitted_rows = sum(t.omitted and not t.duplicate for t in result.transactions)
    for t in result.transactions:
        if t.duplicate or t.omitted:
            continue
        # same form as the map keys (normalize_history); patterns.remove only erases personal data
        historico = normalize_history(patterns.remove(t.historico, names))
        try:
            meio = parser.method_for(historico)
        except UnknownHistory as exc:
            unknown.add(exc.historico)
            continue
        contraparte = (Review(t.review_reason) if t.review_reason
                       else resolve_counterparty(t.contraparte, t.counterparty_document, meio, names))
        if isinstance(contraparte, Review):
            to_review.append({
                "id_usuario": user, "arquivo": rel.arquivo, "data": t.data.isoformat(),
                "historico": historico, "contraparte_original": t.contraparte,
                "valor": f"{t.valor:.2f}", "motivo": contraparte.motivo,
            })
            continue
        # merchant base name and individual on the card machine -> PESSOA_FISICA
        contraparte = merchants.standardize(contraparte, meio, people)
        try:
            lines.append(OutputRow(
                id_usuario=user, data=t.data, historico=historico, contraparte=contraparte,
                valor=t.valor, tipo=TransactionType.INCOME if t.valor > 0 else TransactionType.EXPENSE,
                meio=meio, banco=result.banco,
            ))
        except ValidationError:  # the pydantic message includes the value: do not propagate it
            invalid += 1
        else:
            originals.append({"historico": normalize_history(t.historico), "contraparte": t.contraparte})

    rel.historicos_desconhecidos = len(unknown)
    execution.unknown.extend(
        {"id_usuario": user, "parser": parser.name, "historico": h} for h in sorted(unknown)
    )
    if unknown:
        rel.motivo = "HistoricoDesconhecido"
        return
    if invalid:
        rel.motivo = f"linhas_invalidas:{invalid}"
        return
    rel.linhas_gravadas, rel.linhas_revisar, rel.linhas_duplicadas = len(lines), len(to_review), duplicate_rows
    rel.linhas_omitidas = omitted_rows
    rel.status = ACCEPTED
    execution.lines.extend(lines)
    execution.originals.extend(originals)
    execution.to_review.extend(to_review)


def run(
    source: Path,
    user: str,
    output: Path,
    private_dir: Path,
    parsers: Sequence[type[Parser]] | None = None,
    people: frozenset[str] | None = None,
) -> Execution:
    """`people`: names marked as a person. None = reads the maps from `private_dir`."""
    if not re.fullmatch(r"u\d{2}", user):
        raise ValueError("--usuario deve ser 'u' + 2 dígitos (ex.: u07)")
    return _finalize(_extract_folder(source, parsers), user, output, private_dir, people=people)


def _extract_folder(source: Path, parsers: Sequence[type[Parser]] | None) -> list[_Extracted]:
    """Phase 1: extract and reconcile every file in the folder."""
    return [
        _extract(p, p.relative_to(source).as_posix() if source.is_dir() else p.name, parsers)
        for p in _files(source)
    ]


def _holders(extracted: list[_Extracted]) -> set[str]:
    return {n for e in extracted if e.result for n in e.result.holder_names}


def _finalize(
    extracted: list[_Extracted],
    user: str,
    output: Path,
    private_dir: Path,
    other_holders: set[str] = frozenset(),
    people: frozenset[str] | None = None,
) -> Execution:
    """Phases 2 and 3: anonymize (with this folder's holders + the others') and write."""
    execution = Execution(reports=[e.report for e in extracted])
    execution.holder_names = sorted(_holders(extracted))
    holder_names = sorted(_holders(extracted) | set(other_holders))
    names = patterns.names_regex(holder_names)

    # phase 2: normalize and anonymize (people marked by the user in the data/privado maps)
    people = merchants.declared_people(private_dir) if people is None else people
    for item in extracted:
        if item.result is not None:
            _transform(item, user, names, execution, people)

    _write_private(private_dir / "revisar.csv", user, execution.to_review)
    _write_private(private_dir / "historicos_desconhecidos.csv", user, execution.unknown)

    # phase 3: validate and write (only if some file was accepted)
    if any(r.status == ACCEPTED for r in execution.reports):
        try:
            write_csv(execution.lines, output, holder_names)
        except LeakDetected as exc:
            execution.leak = exc
    _write_report(output.with_name(output.stem + ".relatorio.csv"), execution.reports)
    return execution


@dataclass
class FullExecution:
    """Every folder in data/raw/: one CSV per user + the overall CSV."""

    by_user: dict[str, Execution]
    lines: int = 0
    leak: LeakDetected | None = None

    @property
    def exit_code(self) -> int:
        if self.leak is not None or any(e.leak for e in self.by_user.values()):
            return 2
        return max((e.exit_code for e in self.by_user.values()), default=0)


def user_from_folder(folder: Path) -> str:
    """data/raw/7 -> u07. A folder that is not a number is an error (the pseudonym cannot be guessed)."""
    if not re.fullmatch(r"\d{1,2}", folder.name):
        raise ValueError(f"pasta de usuário deve ser um número de 1 ou 2 dígitos: {folder.name!r}")
    return f"u{int(folder.name):02d}"


def run_all(
    root: Path,
    output_dir: Path,
    overall_output: Path,
    private_dir: Path,
    parsers: Sequence[type[Parser]] | None = None,
) -> FullExecution:
    """Processes each subfolder of `root` as a user and joins everything into a single CSV.

    The overall CSV goes through the validator again, now with the holder names of every
    folder: one user's holder may appear as a counterparty in another user's statement.
    """
    folders = [p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")]
    if not folders:
        raise ValueError("nenhuma pasta de usuário em --raw")
    # 1st extract every folder: one user's holder may be another user's counterparty
    extracted = {user_from_folder(p): _extract_folder(p, parsers) for p in sorted(folders, key=user_from_folder)}
    all_holders = set().union(*(_holders(e) for e in extracted.values()))
    people = merchants.declared_people(private_dir)
    by_user: dict[str, Execution] = {
        u: _finalize(ext, u, output_dir / f"{u}.csv", private_dir, all_holders, people) for u, ext in extracted.items()
    }
    overall = FullExecution(by_user)
    lines = [l for e in by_user.values() if e.leak is None for l in e.lines]
    names = sorted({n for e in by_user.values() for n in e.holder_names})
    try:
        write_csv(lines, overall_output, names)
        overall.lines = len(lines)
    except LeakDetected as exc:
        overall.leak = exc
    return overall


def _write_private(path: Path, user: str, new_rows: list[dict[str, str]]) -> None:
    """Replaces this user's rows and keeps the other users' rows."""
    existing: list[dict[str, str]] = []
    if path.exists():
        with open(path, encoding="utf-8", newline="") as f:
            existing = [r for r in csv.DictReader(f) if r.get("id_usuario") != user]
    all_rows = existing + new_rows
    if not all_rows:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = list(dict.fromkeys(k for r in all_rows for k in r))
    with open(path, "w", encoding="utf-8", newline="") as f:
        csv_writer = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
        csv_writer.writeheader()
        csv_writer.writerows(all_rows)


def _write_report(path: Path, reports: list[FileReport]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        csv_writer = csv.DictWriter(f, fieldnames=[c.name for c in fields(FileReport)], lineterminator="\n")
        csv_writer.writeheader()
        csv_writer.writerows(asdict(r) for r in reports)
