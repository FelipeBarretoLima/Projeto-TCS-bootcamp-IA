"""Bradesco card: merged PDF invoices (2 pages per invoice).

Page rule (defined with the user on 2026-11-04): in each pair of pages, the 2nd ("Página 2 de 2")
has the entries; the 1st ("Página 1 de 2") has only the summary, used here for the check.

Page 1: "Saldo anterior…… R$ S", "(-) …/Pagamentos…… R$ P", "(+)Compras/……… R$ C",
"(=)Total……… R$ T" and the due date (DD/MM/YYYY right below "Total de fatura Vencimento").
Page 2: two columns; the entries are in the left one, read by word position:
    Data | Histórico de Lançamentos | Cidade | US$ | R$      (amount ending in "-" = credit)
Block of each cardholder: "NOME  Cartão 9999 XXXX XXXX 9999" … "Total NOME valor".
End: "Total da fatura em real valor".

Reconciliation, per invoice (rejected alone if it does not balance):
    listed debits == C; listed credits == P; cardholder entries == subtotal;
    S − P + C == T; "Total da fatura em real" == T.
Outside the CSV (but in the check): invoice payment (already in the account statement).
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

_NUM = r"\d{1,3}(?:\.\d{3})*,\d{2}"
_AMOUNT = re.compile(rf"^{_NUM}-?$")
_DATE = re.compile(r"^\d{2}/\d{2}$")
_PAGE = re.compile(r"P[áa]gina (\d) de 2")
_SUMMARY = {
    "saldo": re.compile(rf"^Saldo anterior\.+ R\$ (?P<v>{_NUM})-?$"),
    "pagamentos": re.compile(rf"^\(-\) ?\S*Pagamentos\.+ R\$ (?P<v>{_NUM})$"),
    "compras": re.compile(rf"^\(\+\) ?Compras\S*\.+ R\$ (?P<v>{_NUM})$"),
    "total": re.compile(rf"^\(=\) ?Total\.+ R\$ (?P<v>{_NUM})$"),
}
_DUE_DATE = re.compile(rf"^R\$ {_NUM} (?P<d>\d{{2}}/\d{{2}}/\d{{4}}) R\$")
_LEFT_COLUMN = 358.0  # pt: the right column (summary/fees) starts at ~362
_LINE_TOL = 1.5
_AMOUNT_TOL = (5.0, 15.0)  # amount right-aligned to the header's "R$" (the "-" goes slightly past it)

_PAYMENT = re.compile(r"^PAG(?:TO)?\b")
_INSTALLMENT = re.compile(r"\s*\d{2}/\d{2}$")  # "LOJA 03/10" or glued "LOJA*X03/10"
_FINANCIAL: list[tuple[re.Pattern[str], str, PaymentMethod]] = [
    (re.compile(r"^ANUIDADE\b"), "ANUIDADE", PaymentMethod.FEE),
    (re.compile(r"^(?:IOF)\b"), "IOF", PaymentMethod.INTEREST_IOF),
    (re.compile(r"^(?:JUROS|ENCARGOS|MULTA|MORA)\b"), "JUROS E ENCARGOS", PaymentMethod.INTEREST_IOF),
    (re.compile(r"^ESTORNO\b"), "ESTORNO", PaymentMethod.REFUND),
]
# typical start of a bank entry: if it is not one of the known ones, it is an unknown history
_LOOKS_LIKE_BANK = re.compile(r"^(?:TARIFA|SEGURO|AJUSTE|CRED(?:ITO)?|DEB(?:ITO)?|SALDO|DEVOLUCAO|PROTECAO|"
                              r"SAQUE|TAXA|PARCELAMENTO|ROTATIVO)\b")
_METHODS = {normalize_history(h): m for h, m in [
    ("COMPRA NO CRÉDITO", PaymentMethod.CREDIT_CARD),
    ("COMPRA PARCELADA", PaymentMethod.CREDIT_CARD),
    ("ESTORNO DE COMPRA", PaymentMethod.REFUND),
    ("PAGAMENTO DA FATURA", PaymentMethod.INVOICE_PAYMENT),
    *[(h, m) for _, h, m in _FINANCIAL],
]}


@dataclass
class _Line:
    top: float
    words: list[dict]

    def text(self, x_min: float = -1, x_max: float = 1e9) -> str:
        return " ".join(w["text"] for w in self.words if w["x0"] >= x_min and w["x1"] <= x_max)


@dataclass
class _Invoice:
    page: int
    due_date: date
    summary: dict[str, Decimal]
    entries: list[tuple[int, date, str, Decimal, int | None]] = field(default_factory=list)
    cardholders: list[Decimal] = field(default_factory=list)
    page2_total: Decimal | None = None


class BradescoCardPdf(Parser):
    name = "bradesco_cartao_pdf"
    banco = "bradesco"
    product = "cartao"
    METHODS = _METHODS
    REJECT_BY_DOCUMENT = True

    @classmethod
    def detect(cls, path: Path) -> bool:
        if path.suffix.lower() != ".pdf":
            return False
        pages = pdf_text(path, 1)
        if not pages:
            return False
        t = pages[0]
        return ("Fatura Mensal" in t and bool(_PAGE.search(t)) and "Total de fatura Vencimento" in t
                and any(rx.match(l) for l in t.splitlines() for rx in (_SUMMARY["saldo"],)))

    def extract(self, path: Path) -> ExtractionResult:
        import pdfplumber

        invoices: list[_Invoice] = []
        holders: set[str] = set()
        with pdfplumber.open(path) as pdf:
            if len(pdf.pages) % 2:
                raise UnexpectedLayout(self.name, "numero_de_paginas_impar")
            for k in range(0, len(pdf.pages), 2):
                p1, p2 = pdf.pages[k], pdf.pages[k + 1]
                t1, t2 = p1.extract_text() or "", p2.extract_text() or ""
                m1, m2 = _PAGE.search(t1), _PAGE.search(t2)
                if not (m1 and m1.group(1) == "1" and m2 and m2.group(1) == "2"):
                    raise UnexpectedLayout(self.name, "par_de_paginas", k + 1)
                inv = self._read_summary(t1, k + 1)
                self._read_entries(p2, k + 2, inv, holders)
                invoices.append(inv)
        return self._result(invoices, sorted(holders))

    # --- page 1 ---

    def _read_summary(self, text: str, num: int) -> _Invoice:
        summary: dict[str, Decimal] = {}
        due_date: date | None = None
        lines = text.splitlines()
        for i, l in enumerate(lines):
            for key, rx in _SUMMARY.items():
                if (m := rx.match(l)) and key not in summary:
                    v = br_amount(m["v"])
                    summary[key] = -v if key == "saldo" and l.endswith("-") else v
            if l.startswith("Total de fatura Vencimento") and i + 1 < len(lines):
                if m := _DUE_DATE.match(lines[i + 1]):
                    due_date = datetime.strptime(m["d"], "%d/%m/%Y").date()
        if set(summary) != set(_SUMMARY):
            raise UnexpectedLayout(self.name, "resumo_incompleto", num)
        if due_date is None:
            raise UnexpectedLayout(self.name, "vencimento", num)
        return _Invoice(num, due_date, summary)

    # --- page 2 ---

    def _read_entries(self, page, num: int, inv: _Invoice, holders: set[str]) -> None:
        lines = self._lines([w for w in page.extract_words() if w["x1"] <= _LEFT_COLUMN])
        hdr = next((l for l in lines if l.text().startswith("Data Histórico de Lançamentos")), None)
        if hdr is None:
            raise UnexpectedLayout(self.name, "cabecalho_dos_lancamentos", num)
        ws = hdr.words
        texts = [w["text"] for w in ws]
        i_entry = texts.index("Lançamentos")
        x_hist = ws[texts.index("Histórico")]["x0"] - 2
        x_city = ws[i_entry + 1]["x0"] - 2  # column right after "Lançamentos" (city)
        x_rs = ws[-1]["x1"]  # last title: "R$"
        x_usd = ws[-2]["x1"]  # second to last: "US$"

        block: int | None = None
        for l in lines:
            if l.top <= hdr.top:
                continue
            t = [w["text"] for w in l.words]
            amounts = [w for w in l.words if _AMOUNT.match(w["text"])
                       and x_rs - _AMOUNT_TOL[0] <= w["x1"] <= x_rs + _AMOUNT_TOL[1]]
            if t[0] == "Total":
                if not amounts:
                    raise UnexpectedLayout(self.name, "total_sem_valor", num)
                v = self._amount(amounts[-1]["text"])
                if t[1:4] == ["da", "fatura", "em"]:
                    inv.page2_total = v
                elif block is not None:
                    inv.cardholders[block] = v
                    block = None
                else:
                    raise UnexpectedLayout(self.name, "subtotal_sem_portador", num)
                continue
            if "Cartão" in t and l.words[t.index("Cartão")]["x0"] >= x_city - 10:
                name = " ".join(w["text"] for w in l.words if w["x1"] <= l.words[t.index("Cartão")]["x0"])
                if name:
                    holders.add(name)
                inv.cardholders.append(Decimal("NaN"))  # filled by "Total NOME"
                block = len(inv.cardholders) - 1
                continue
            if _DATE.match(t[0]) and l.words[0]["x0"] < x_hist - 5:  # date starts before the history
                if len(amounts) != 1:
                    raise UnexpectedLayout(self.name, "lancamento_sem_valor_unico", num)
                if any(_AMOUNT.match(w["text"]) and abs(w["x1"] - x_usd) <= 15 for w in l.words):
                    raise UnexpectedLayout(self.name, "lancamento_em_dolar", num)  # not seen yet
                historico = l.text(x_min=x_hist, x_max=x_city)
                if not historico:
                    raise UnexpectedLayout(self.name, "lancamento_sem_historico", num)
                data = self._date(t[0], inv.due_date, num)
                inv.entries.append((num, data, historico, self._amount(amounts[0]["text"]), block))
                continue
            if any(_AMOUNT.match(w["text"]) for w in amounts):
                raise UnexpectedLayout(self.name, "valor_fora_de_lancamento", num)
            # other lines in the column: title, messages and legal text

    @staticmethod
    def _lines(words: list[dict]) -> list[_Line]:
        lines: list[_Line] = []
        for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
            if lines and w["top"] - lines[-1].top <= _LINE_TOL:
                lines[-1].words.append(w)
            else:
                lines.append(_Line(w["top"], [w]))
        for l in lines:
            l.words.sort(key=lambda w: w["x0"])
        return lines

    @staticmethod
    def _amount(text: str) -> Decimal:
        """Amount as on the invoice: charge > 0, credit ("999,99-") < 0."""
        return br_amount(text)

    def _date(self, ddmm: str, due_date: date, num: int) -> date:
        """Year of a DD/MM date: the most recent one that does not go past the due date.

        Installments show the original purchase date, which may be in the same month as the due
        date but a year earlier (e.g. due 05/10, installment of a purchase made on 12/10 of the previous year).
        """
        day, month = int(ddmm[:2]), int(ddmm[3:])
        try:
            d = date(due_date.year, month, day)
            if d > due_date:
                d = date(due_date.year - 1, month, day)
        except ValueError:
            raise UnexpectedLayout(self.name, "data", num) from None
        return d

    # --- assembly and check ---

    def _result(self, invoices: list[_Invoice], holders: list[str]) -> ExtractionResult:
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
                Segment(f"{doc} débitos", Decimal(0), -r["compras"], doc),
                Segment(f"{doc} créditos", Decimal(0), r["pagamentos"], doc),
                # no entries: only balances if the summary itself is consistent
                Segment(f"{doc} resumo", r["saldo"] - r["pagamentos"] + r["compras"], r["total"], doc),
                Segment(f"{doc} total da página 2", f.page2_total if f.page2_total is not None
                         else Decimal("NaN"), r["total"], doc),
            ]
            i_holder = len(segmentos)
            segmentos += [Segment(f"{doc} portador {j}", Decimal(0), -sub, doc)
                          for j, sub in enumerate(f.cardholders)]
            for num, data, historico, v, block in f.entries:
                h, contraparte, omitted = self._classify(historico, v)
                segs: tuple[int, ...] = (i0 if v > 0 else i0 + 1,)
                if block is not None:
                    segs += (i_holder + block,)
                transactions.append(RawTransaction(data, h, -v, segs, contraparte, page=num,
                                                 omitted=omitted or v == 0))
        return ExtractionResult(self.banco, self.product, transactions, segmentos, holders)

    @staticmethod
    def _classify(historico: str, v: Decimal) -> tuple[str, str, bool]:
        """(canonical history, counterparty, omitted). v as on the invoice (charge > 0)."""
        if _PAYMENT.match(historico):
            return "PAGAMENTO DA FATURA", "", True
        for rx, h, _ in _FINANCIAL:
            if rx.match(historico):
                return h, "", False
        if _LOOKS_LIKE_BANK.match(historico):
            return historico, "", False  # unknown bank entry: the map rejects it
        installment = bool(_INSTALLMENT.search(historico))
        store = _INSTALLMENT.sub("", historico).strip()
        if v < 0:
            return "ESTORNO DE COMPRA", store, False
        return ("COMPRA PARCELADA" if installment else "COMPRA NO CRÉDITO"), store, False
