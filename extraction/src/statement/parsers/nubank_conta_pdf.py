"""Nubank account: PDF statement (one or several statements merged in the same file).

Layout of each page:
    0  HOLDER NAME
    1  CPF •••.123.456-•• Agência 0001 Conta
    2  12345678-9
    3  01 DE JANEIRO DE 2026 a 31 DE JANEIRO DE 2026 VALORES EM R$
    …  body
    fixed footer ("Tem alguma dúvida?…", "Extrato gerado dia…")
First page of each statement: summary (opening balance, yield, income, expenses,
final balance) and "Movimentações". Body: groups "DD MMM AAAA Total de entradas|saídas ± X"
(the date disappears for the 2nd group of the same day) with entries "Tipo complemento 1.234,56";
the complement may continue on the following lines (without an amount at the end).

Reconciliation, each entry in three segments:
    day group (0 -> ±group total), statement total of income/expenses,
    opening balance + net yield + entries == final balance.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

from ..normalization import br_amount
from . import nubank_common as nu
from .base import UnexpectedLayout, Parser, ExtractionResult, Segment, RawTransaction, pdf_text

_MONTHS = {m: i for i, m in enumerate("JAN FEV MAR ABR MAI JUN JUL AGO SET OUT NOV DEZ".split(), start=1)}
_MONTHS_LONG = ("JANEIRO FEVEREIRO MARÇO ABRIL MAIO JUNHO JULHO AGOSTO SETEMBRO OUTUBRO NOVEMBRO DEZEMBRO").split()

_NUM = r"\d{1,3}(?:\.\d{3})*,\d{2}"
_HDR_CPF = re.compile(r"^CPF •••\.\d{3}\.\d{3}-•• Agência \d{4} Conta$")
_HDR_ACCOUNT = re.compile(r"^\d+-\d$")
_MONTH_LONG = "(?:" + "|".join(_MONTHS_LONG) + ")"
_HDR_PERIOD = re.compile(rf"^\d{{2}} DE {_MONTH_LONG} DE \d{{4}} a \d{{2}} DE {_MONTH_LONG} DE \d{{4}} VALORES EM R\$$")

_GROUP = re.compile(rf"^(?:(?P<d>\d{{2}}) (?P<m>{'|'.join(_MONTHS)}) (?P<a>\d{{4}}) )?"
                    rf"Total de (?P<lado>entradas|saídas) (?P<sinal>[+-]) (?P<v>{_NUM})$")
# date alone at the end of the page: that group's "Total de …" comes at the top of the next page
_DATE_ONLY = re.compile(rf"^(?P<d>\d{{2}}) (?P<m>{'|'.join(_MONTHS)}) (?P<a>\d{{4}})$")
_ENTRY = re.compile(rf"^(?P<texto>.+?) (?P<v>{_NUM})$")

_SUMMARY = {
    "inicial": re.compile(rf"^Saldo inicial (?P<v>-?{_NUM})$"),
    "rendimento": re.compile(rf"^Rendimento líquido (?P<v>[+-]{_NUM})$"),
    "entradas": re.compile(rf"^(?:R\$ -?{_NUM} )?Total de entradas (?P<v>\+{_NUM})$"),
    "saidas": re.compile(rf"^Total de saídas (?P<v>-{_NUM})$"),
    "final": re.compile(rf"^Saldo final do período (?P<v>-?{_NUM})$"),
}
_FIXED_SUMMARY = {"Saldo final do período", "Movimentações"}
_FOOTER = ("Tem alguma dúvida?", "metropolitanas)", "Caso a solução fornecida",
           "disponíveis em nubank.com.br", "Extrato gerado dia ")
_FINAL_NOTICE = "O saldo líquido"  # block of legal notices at the end of each statement


@dataclass
class _Statement:
    summary: dict[str, Decimal] = field(default_factory=dict)
    idx_statement: int = -1
    idx_income: int = -1
    idx_expense: int = -1


class NubankAccountPdf(Parser):
    name = "nubank_conta_pdf"
    banco = "nubank"
    product = "conta"
    METHODS = nu.METHODS

    @classmethod
    def detect(cls, path: Path) -> bool:
        if path.suffix.lower() != ".pdf":
            return False
        pages = pdf_text(path, 1)
        if not pages:
            return False
        lines = pages[0].splitlines()
        return (
            len(lines) > 4
            and bool(_HDR_CPF.match(lines[1]))
            and bool(_HDR_PERIOD.match(lines[3]))
            and any(l.startswith("disponíveis em nubank.com.br") for l in lines)
        )

    def extract(self, path: Path) -> ExtractionResult:
        pages = pdf_text(path)
        segmentos: list[Segment] = []
        transactions: list[RawTransaction] = []
        holders: set[str] = set()
        extrato: _Statement | None = None
        group_date: date | None = None
        group: tuple[int, int] | None = None  # (segment index, sign)
        # entry being assembled: (page, date, sign, segments, text, amount)
        pending: list | None = None

        def close_pending() -> None:
            nonlocal pending
            if pending is not None:
                transactions.append(self._build(*pending))
                pending = None

        for num, text in enumerate(pages, start=1):
            lines = text.splitlines()
            if len(lines) < 4 or not _HDR_CPF.match(lines[1]) or not _HDR_ACCOUNT.match(lines[2]) \
                    or not _HDR_PERIOD.match(lines[3]):
                raise UnexpectedLayout(self.name, "cabecalho", num)
            holders.add(lines[0].strip())
            body = lines[4:]

            # summary page = start of a new statement
            if body and _SUMMARY["inicial"].match(body[0]):
                close_pending()
                extrato, body = self._read_summary(body, segmentos, num)
                group_date, group = None, None
            if extrato is None:
                raise UnexpectedLayout(self.name, "extrato_sem_resumo", num)

            in_notice = False
            for line in body:
                if in_notice or line.startswith(_FINAL_NOTICE):
                    in_notice = True  # the rest of the page is legal notices
                    continue
                if line.startswith(_FOOTER):
                    continue
                if m := _GROUP.match(line):
                    close_pending()
                    if m["d"]:
                        group_date = date(int(m["a"]), _MONTHS[m["m"]], int(m["d"]))
                    elif group_date is None:
                        raise UnexpectedLayout(self.name, "grupo_sem_data", num)
                    sign = 1 if m["lado"] == "entradas" else -1
                    if (m["sinal"] == "+") != (sign > 0):
                        raise UnexpectedLayout(self.name, "sinal_do_grupo", num)
                    segmentos.append(Segment(f"grupo {group_date.isoformat()} {m['lado']}",
                                              Decimal(0), sign * br_amount(m["v"])))
                    group = (len(segmentos) - 1, sign)
                    continue
                if m := _DATE_ONLY.match(line):
                    close_pending()
                    group_date = date(int(m["a"]), _MONTHS[m["m"]], int(m["d"]))
                    group = None  # an entry before "Total de …" is an error
                    continue
                if m := _ENTRY.match(line):
                    close_pending()
                    if group is None or group_date is None:
                        raise UnexpectedLayout(self.name, "lancamento_fora_de_grupo", num)
                    idx_side = extrato.idx_income if group[1] > 0 else extrato.idx_expense
                    segs = (group[0], idx_side, extrato.idx_statement)
                    pending = [num, group_date, group[1], segs, m["texto"], br_amount(m["v"])]
                    continue
                # continuation of the previous entry's complement
                if pending is None:
                    raise UnexpectedLayout(self.name, "linha_solta", num)
                pending[4] += " " + line.strip()
        close_pending()
        if not transactions:
            raise UnexpectedLayout(self.name, "arquivo_sem_lancamentos")
        if len(holders) != 1:
            raise UnexpectedLayout(self.name, "titular_diferente_entre_paginas")
        return ExtractionResult(self.banco, self.product, transactions, segmentos, sorted(holders))

    def _read_summary(self, body: list[str], segmentos: list[Segment], num: int) -> tuple[_Statement, list[str]]:
        extrato = _Statement()
        for i, line in enumerate(body):
            if line == "Movimentações":
                break
            key = next((k for k, rx in _SUMMARY.items() if rx.match(line)), None)
            if key is not None:
                if key in extrato.summary:
                    if key != "final" or extrato.summary[key] != br_amount(_SUMMARY[key].match(line)["v"]):
                        raise UnexpectedLayout(self.name, "resumo_repetido", num)
                extrato.summary[key] = br_amount(_SUMMARY[key].match(line)["v"])
            elif line not in _FIXED_SUMMARY:
                raise UnexpectedLayout(self.name, "linha_desconhecida_no_resumo", num)
        else:
            raise UnexpectedLayout(self.name, "resumo_sem_movimentacoes", num)
        if set(extrato.summary) != set(_SUMMARY):
            raise UnexpectedLayout(self.name, "resumo_incompleto", num)
        r = extrato.summary
        n = len(segmentos)
        segmentos += [
            Segment(f"extrato {n} saldo", r["inicial"] + r["rendimento"], r["final"]),
            Segment(f"extrato {n} entradas", Decimal(0), r["entradas"]),
            Segment(f"extrato {n} saidas", Decimal(0), r["saidas"]),
        ]
        extrato.idx_statement, extrato.idx_income, extrato.idx_expense = n, n + 1, n + 2
        return extrato, body[i + 1:]

    def _build(self, page: int, data: date, sign: int, segs: tuple[int, ...], text: str,
               valor: Decimal) -> RawTransaction:
        text = nu.undo_interleaving(re.sub(r"\s+", " ", text).strip())
        tipo, rest = nu.split_type(text)
        name = doc = ""
        if tipo in nu.TYPES:
            if nu.TYPES[tipo].sign != sign:
                raise UnexpectedLayout(self.name, "tipo_no_grupo_errado", page)
            try:
                name, doc = nu.contraparte(tipo, rest)
            except nu.InvalidComplement as exc:
                raise UnexpectedLayout(self.name, str(exc), page) from None
        return RawTransaction(data, tipo, sign * valor, segs, name, doc, page=page)
