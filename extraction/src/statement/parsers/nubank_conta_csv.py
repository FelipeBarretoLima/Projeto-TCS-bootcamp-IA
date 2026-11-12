"""Nubank account: CSV exported by the app (Data,Valor,Identificador,Descrição).

The file has no balance or total: it is accepted with reconciliation "sem_totais".
Checks that can be done: exact header, date/amount/identifier format
and sign consistent with the entry type.
"""

from __future__ import annotations

import csv
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from .base import UnexpectedLayout, Parser, ExtractionResult, RawTransaction, first_line
from . import nubank_common as nu

HEADER = "Data,Valor,Identificador,Descrição"
_AMOUNT = re.compile(r"^-?\d+\.\d{2}$")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class NubankAccountCsv(Parser):
    name = "nubank_conta_csv"
    banco = "nubank"
    product = "conta"
    METHODS = nu.METHODS
    NO_TOTALS = True

    @classmethod
    def detect(cls, path: Path) -> bool:
        return path.suffix.lower() == ".csv" and first_line(path) == HEADER

    def extract(self, path: Path) -> ExtractionResult:
        transactions = []
        with open(path, encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            if next(reader) != HEADER.split(","):
                raise UnexpectedLayout(self.name, "cabecalho")
            for n, line in enumerate(reader, start=2):
                transactions.append(self._line(line, n))
        if not transactions:
            raise UnexpectedLayout(self.name, "arquivo_sem_lancamentos")
        return ExtractionResult(self.banco, self.product, transactions, segmentos=[])

    def _line(self, line: list[str], n: int) -> RawTransaction:
        # n = line number in the file, used as "page" in error messages
        if len(line) != 4:
            raise UnexpectedLayout(self.name, "numero_de_colunas", n)
        date_txt, amount_txt, ident, description = line
        try:
            data = datetime.strptime(date_txt, "%d/%m/%Y").date()
        except ValueError:
            raise UnexpectedLayout(self.name, "data", n) from None
        if not _AMOUNT.match(amount_txt):
            raise UnexpectedLayout(self.name, "valor", n)
        if not _UUID.match(ident):
            raise UnexpectedLayout(self.name, "identificador", n)
        valor = Decimal(amount_txt)

        # in the CSV the type is separated from the rest by " - "
        tipo, rest = nu.split_type(description)
        if tipo in nu.TYPES:
            if rest and not rest.startswith("- "):
                raise UnexpectedLayout(self.name, "separador_do_tipo", n)
            if (valor > 0) != (nu.TYPES[tipo].sign > 0):
                raise UnexpectedLayout(self.name, "sinal_incoerente_com_tipo", n)
            try:
                name, doc = nu.contraparte(tipo, rest)
            except nu.InvalidComplement as exc:
                raise UnexpectedLayout(self.name, str(exc), n) from None
        else:
            tipo, name, doc = description.split(" - ", 1)[0], "", ""
        return RawTransaction(data, tipo, valor, 0, name, doc, page=n)
