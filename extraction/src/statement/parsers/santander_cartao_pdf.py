"""Santander card: merged PDF invoices.

Each invoice: cover (no pagination), "1/N" (due date and total to pay), "2/N" (entries and
Resumo da Fatura) and, sometimes, "3/3" (legal text). Page rule (defined with the user on
2026-11-04): the entries are on the page after "1/N" — the 3rd of each group of 4.
Pages that do not belong to any "1/N" group (e.g. an old invoice, with another layout, at the end of the
file) become a rejected document, recorded in the report.

Entries page: two independent columns (cut at x=300), read top to bottom.
Entry: "[icon] DD/MM description [installment DD/DD] [-]amount" (amount = rightmost number).
Resumo da Fatura: Saldo Anterior; (+) Total … no Brasil; (+) Total … no Exterior;
(-) Total de pagamentos; (-) Total de créditos; (=) Saldo Desta Fatura.

Reconciliation, per invoice (rejected alone if it does not balance):
    listed debits == Brasil + Exterior; listed payments == Total de pagamentos;
    other listed credits == Total de créditos; Saldo Anterior + debits − payments − credits == Saldo.
Outside the CSV (but in the check): invoice payment.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from ..models import PaymentMethod
from ..normalization import normalize_history, br_amount
from .base import UnexpectedLayout, Parser, ExtractionResult, Segment, RawTransaction, pdf_text

_NUM_RX = r"-?\d{1,3}(?:\.\d{3})*,\d{2}"
_NUM = re.compile(rf"^{_NUM_RX}$")
_DATE = re.compile(r"^\d{2}/\d{2}$")
_ICON = re.compile(r"^\d$")
_PAGINATION = re.compile(r"^(\d)/(\d)$")
# "R$ total DD/MM/AAAA R$limite" or "R$ total DD/MM/AAAA DD/MM/AAAA" (due date = 1st date)
_DUE_DATE = re.compile(rf"^R\$ {_NUM_RX} (?P<d>\d{{2}}/\d{{2}}/\d{{4}}) (?:R\$|\d{{2}}/\d{{2}}/\d{{4}})")
_HOLDER = re.compile(r"cartão SANTANDER (?P<nome>.+?) - \d{4}\b")
_CARD = re.compile(r"^(?P<nome>.+?) - \d{4} \S+ \S+ \d{4}\b")
_COLUMN_CUT = 300.0
_LINE_TOL = 2.0
_SUMMARY = {
    "saldo": re.compile(r"^Saldo Anterior\b"),
    "brasil": re.compile(r"^\(\+\) Total .* no Brasil\b"),
    "exterior": re.compile(r"^\(\+\) Total .* no (?!Brasil)\S+"),
    "pagamentos": re.compile(r"^\(-\) Total de pagamentos\b"),
    "creditos": re.compile(r"^\(-\) Total de cr"),
    "total": re.compile(r"^\(=\) Saldo\b"),
}
_PAYMENT = re.compile(r"^PAGAMENTO DE FATURA\b")
_INSTALLMENT = re.compile(r"\s*\d{2}/\d{2}$")
_FINANCIAL: list[tuple[re.Pattern[str], str, PaymentMethod]] = [
    (re.compile(r"^ANUIDADE\b"), "ANUIDADE", PaymentMethod.FEE),
    (re.compile(r"^IOF\b"), "IOF", PaymentMethod.INTEREST_IOF),
    (re.compile(r"^(?:JUROS|ENCARGOS|MULTA|MORA)\b"), "JUROS E ENCARGOS", PaymentMethod.INTEREST_IOF),
    (re.compile(r"^ESTORNO\b"), "ESTORNO", PaymentMethod.REFUND),
]
_LOOKS_LIKE_BANK = re.compile(r"^(?:TARIFA|SEGURO|AJUSTE|CRED(?:ITO)?|DEB(?:ITO)?|SALDO|DEVOLUCAO|PROTECAO|"
                              r"SAQUE|TAXA|PARCELAMENTO|ROTATIVO|PAGAMENTO)\b")
_METHODS = {normalize_history(h): m for h, m in [
    ("COMPRA NO CRÉDITO", PaymentMethod.CREDIT_CARD),
    ("COMPRA PARCELADA", PaymentMethod.CREDIT_CARD),
    ("ESTORNO DE COMPRA", PaymentMethod.REFUND),
    ("PAGAMENTO DA FATURA", PaymentMethod.INVOICE_PAYMENT),
    *[(h, m) for _, h, m in _FINANCIAL],
]}


@dataclass
class _Invoice:
    page: int
    due_date: date
    summary: dict[str, Decimal] = field(default_factory=dict)
    entries: list[tuple[int, date, str, Decimal]] = field(default_factory=list)


class SantanderCardPdf(Parser):
    name = "santander_cartao_pdf"
    banco = "santander"
    product = "cartao"
    METHODS = _METHODS
    REJECT_BY_DOCUMENT = True

    @classmethod
    def detect(cls, path: Path) -> bool:
        if path.suffix.lower() != ".pdf":
            return False
        pages = pdf_text(path, 2)
        if len(pages) < 2:
            return False
        ls = pages[1].splitlines()
        return (bool(ls) and bool(_PAGINATION.match(ls[0].strip())) and ls[0].strip().startswith("1/")
                and "cartão SANTANDER" in pages[1] and "Total a Pagar" in pages[1])

    def extract(self, path: Path) -> ExtractionResult:
        import pdfplumber

        texts = pdf_text(path)
        invoices: list[_Invoice] = []
        holders: set[str] = set()
        covered: set[int] = set()  # pages (1-based) that belong to some recognized group
        with pdfplumber.open(path) as pdf:
            for i, t in enumerate(texts):
                ls = t.splitlines()
                m = _PAGINATION.match(ls[0].strip()) if ls else None
                if not (m and m.group(1) == "1"):
                    continue
                total_pages = int(m.group(2))
                num = i + 1  # page "1/N"
                if num + 1 > len(texts):
                    raise UnexpectedLayout(self.name, "fatura_sem_pagina_de_lancamentos", num)
                covered.update(range(num - 1, num + total_pages))  # cover + N pages
                inv = self._read_inner_cover(t, num, holders)
                self._read_entries(pdf.pages[i + 1], num + 1, inv, holders)
                invoices.append(inv)
        if not invoices:
            raise UnexpectedLayout(self.name, "sem_faturas")
        loose = sorted(set(range(1, len(texts) + 1)) - covered)
        return self._result(invoices, sorted(holders), loose)

    # --- page 1/N ---

    def _read_inner_cover(self, text: str, num: int, holders: set[str]) -> _Invoice:
        due = next((m for l in text.splitlines() if (m := _DUE_DATE.match(l))), None)
        if due is None:
            raise UnexpectedLayout(self.name, "vencimento", num)
        if m := _HOLDER.search(text):
            holders.add(m["nome"].strip())
        return _Invoice(num, datetime.strptime(due["d"], "%d/%m/%Y").date())

    # --- entries page ---

    def _read_entries(self, page, num: int, inv: _Invoice, holders: set[str]) -> None:
        words = page.extract_words()
        for column in ([w for w in words if w["x0"] < _COLUMN_CUT],
                       [w for w in words if w["x0"] >= _COLUMN_CUT]):
            for line in self._lines(column):
                self._read_line(line, num, inv, holders)
        if set(inv.summary) != set(_SUMMARY):
            raise UnexpectedLayout(self.name, "resumo_incompleto", num)

    def _read_line(self, ws: list[dict], num: int, inv: _Invoice, holders: set[str]) -> None:
        t = [w["text"] for w in ws]
        txt = " ".join(t)
        nums = [w for w in ws if _NUM.match(w["text"])]
        key = next((k for k, rx in _SUMMARY.items() if rx.match(txt)), None)
        if key is not None:
            if len(nums) != 1 or key in inv.summary:
                raise UnexpectedLayout(self.name, f"resumo_{key}", num)
            inv.summary[key] = br_amount(nums[0]["text"])
            return
        if m := _CARD.match(txt):
            holders.add(m["nome"].strip())
            return
        i = 1 if len(t) > 1 and _ICON.match(t[0]) and _DATE.match(t[1]) else 0
        if _DATE.match(t[i]):
            if len(nums) != 1 or ws[-1] is not nums[0]:
                raise UnexpectedLayout(self.name, "lancamento_sem_valor_unico_no_fim", num)
            desc = " ".join(t[i + 1:-1])
            if not desc:
                raise UnexpectedLayout(self.name, "lancamento_sem_descricao", num)
            inv.entries.append((num, self._date(t[i], inv.due_date, num), desc, br_amount(nums[0]["text"])))
            return
        # other lines: titles, table headers, VALOR TOTAL per card, table of
        # future installments and legal text — none of them is an entry

    @staticmethod
    def _lines(words: list[dict]) -> list[list[dict]]:
        lines: list[list[dict]] = []
        tops: list[float] = []
        for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
            if lines and w["top"] - tops[-1] <= _LINE_TOL:
                lines[-1].append(w)
            else:
                lines.append([w])
                tops.append(w["top"])
        return [sorted(l, key=lambda w: w["x0"]) for l in lines]

    def _date(self, ddmm: str, due_date: date, num: int) -> date:
        """The most recent year that does not go past the due date (installments carry the purchase date)."""
        day, month = int(ddmm[:2]), int(ddmm[3:])
        try:
            d = date(due_date.year, month, day)
            return d if d <= due_date else date(due_date.year - 1, month, day)
        except ValueError:
            raise UnexpectedLayout(self.name, "data", num) from None

    # --- assembly and check ---

    def _result(self, invoices: list[_Invoice], holders: list[str], loose: list[int]) -> ExtractionResult:
        transactions: list[RawTransaction] = []
        segmentos: list[Segment] = []
        seen: set[date] = set()
        for f in invoices:
            if f.due_date in seen:
                raise UnexpectedLayout(self.name, "fatura_repetida", f.page)
            seen.add(f.due_date)
            doc = f"fatura {f.due_date.isoformat()}"
            r = f.summary
            i0 = len(segmentos)
            segmentos += [
                Segment(f"{doc} débitos", Decimal(0), -(r["brasil"] + r["exterior"]), doc),
                Segment(f"{doc} pagamentos", Decimal(0), r["pagamentos"], doc),
                Segment(f"{doc} créditos", Decimal(0), r["creditos"], doc),
                # no entries: only balances if the summary itself is consistent
                Segment(f"{doc} resumo", r["saldo"] + r["brasil"] + r["exterior"] - r["pagamentos"] - r["creditos"],
                         r["total"], doc),
            ]
            for num, data, desc, v in f.entries:
                h, contraparte, omitted = self._classify(desc, v)
                seg = i0 if v > 0 else (i0 + 1 if h == "PAGAMENTO DA FATURA" else i0 + 2)
                transactions.append(RawTransaction(data, h, -v, (seg,), contraparte, page=num,
                                                 omitted=omitted or v == 0))
        if loose:
            # pages outside any "1/N" group (e.g. old-layout invoice): rejected document
            doc = f"páginas {loose[0]}-{loose[-1]} fora do layout (ignoradas)"
            segmentos.append(Segment(doc, Decimal("NaN"), Decimal(0), doc))
        return ExtractionResult(self.banco, self.product, transactions, segmentos, holders)

    @staticmethod
    def _classify(desc: str, v: Decimal) -> tuple[str, str, bool]:
        """(canonical history, counterparty, omitted). v as on the invoice (charge > 0)."""
        if _PAYMENT.match(desc):
            return "PAGAMENTO DA FATURA", "", True
        for rx, h, _ in _FINANCIAL:
            if rx.match(desc):
                return h, "", False
        if _LOOKS_LIKE_BANK.match(desc):
            return desc, "", False  # unknown bank entry: the map rejects it
        installment = bool(_INSTALLMENT.search(desc))
        store = _INSTALLMENT.sub("", desc).strip()
        if v < 0:
            return "ESTORNO DE COMPRA", store, False
        return ("COMPRA PARCELADA" if installment else "COMPRA NO CRÉDITO"), store, False
