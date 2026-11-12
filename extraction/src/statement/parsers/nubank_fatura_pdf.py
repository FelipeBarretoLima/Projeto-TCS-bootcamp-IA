"""Nubank card: PDF invoices (one or several merged in the same file).

Each invoice starts with a cover ("<name>, …" / "Esta é a sua fatura de" / … / "Data de vencimento:
DD MMM AAAA"). Then: the RESUMO DA FATURA page, the section "TRANSAÇÕES DE DD MMM A DD MMM"
and pages of standard text. Inner pages start with "NOME DO TITULAR" / "FATURA DD MMM AAAA
EMISSÃO E ENVIO …". In the transactions section there are blocks per cardholder ("NOME R$ subtotal") and the block
"Pagamentos e Financiamentos"; entry = "DD MMM description [−]R$ amount" (no year).

Reconciliation, per invoice (data from the summary itself, which Nubank declares):
  listed charges == sum of the summary items except "Fatura anterior", "Pagamento recebido",
                    "Saldo financiado" (previous debt that went to financing) and the total;
  listed payments == "Pagamento recebido";
  entries of each cardholder == cardholder subtotal.
"Total a pagar" is not included: it depends on credit accumulated from previous invoices and on
financing (bank rules that do not show up entry by entry).

Outside the CSV (but inside reconciliation): invoice payment (already in the account statement),
remaining balance of the previous invoice and revolving balance movements.
Sign: a charge on the invoice becomes an expense (negative); a credit on the invoice becomes income (positive).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

from ..models import PaymentMethod
from ..normalization import normalize_history, br_amount
from .base import UnexpectedLayout, Parser, ExtractionResult, Segment, RawTransaction, pdf_text

_MONTHS = {m: i for i, m in enumerate("JAN FEV MAR ABR MAI JUN JUL AGO SET OUT NOV DEZ".split(), start=1)}
_M = "(?:" + "|".join(_MONTHS) + ")"
_NUM = r"\d{1,3}(?:\.\d{3})*,\d{2}"
_V = rf"(?P<s>[−-])?R\$ (?P<v>{_NUM})"

_COVER = re.compile(r"^.+ é a .+ fatura de$")  # 2nd line of the cover
_DUE_DATE = re.compile(rf"^Data de vencimento: (?P<d>\d{{2}}) (?P<m>{_M}) (?P<a>\d{{4}})$")
_HDR_INTERNAL = re.compile(rf"^FATURA \d{{2}} {_M} \d{{4}} EMISSÃO E ENVIO \d{{2}} {_M} \d{{4}}$")
_SECTION = re.compile(rf"^TRANSAÇÕES DE \d{{2}} {_M} A \d{{2}} {_M}$")
_ENTRY = re.compile(rf"^(?P<dd>\d{{2}}) (?P<mm>{_M}) (?P<d>.+?) {_V}$")
_LOOKS_LIKE_ENTRY = re.compile(rf"^\d{{2}} {_M} ")
# cardholder block header: "Cardholder Name R$ subtotal" (label without digits), followed by an entry
_CARDHOLDER = re.compile(rf"^(?P<nome>[^\W\d_][^\d•$]*?) R\$ (?P<v>{_NUM})$")
_PAYMENTS_BLOCK = re.compile(rf"^Pagamentos(?: e Financiamentos)? {_V}$")
_SUMMARY_ITEM = re.compile(rf"^(?P<t>.+?) {_V}$")
_SUMMARY_END = ("Pagamento mínimo", "O Nubank")
# summary labels (lowercase, up to the comma) -> included in the sum of charges?
_SUMMARY: dict[str, bool] = {
    "fatura anterior": False,
    "pagamento recebido": False,
    "saldo financiado": False,
    "total a pagar": False,
    "total de compras de todos os cartões": True,
    "outros lançamentos": True,
    "juros de financiamento": True,
    "iof de financiamento": True,
    "iof de compras internacionais": True,
    "estorno de juros": True,
}

# fixed descriptions -> (history, method, omitted)
_FIXED: dict[str, tuple[str, PaymentMethod, bool]] = {
    "Saldo restante da fatura anterior": ("SALDO RESTANTE DA FATURA ANTERIOR", PaymentMethod.OTHER, True),
    "Saldo em rotativo": ("SALDO EM ROTATIVO", PaymentMethod.OTHER, True),
    "Crédito de rotativo": ("CRÉDITO DE ROTATIVO", PaymentMethod.OTHER, True),
    "Encerramento de dívida": ("ENCERRAMENTO DE DÍVIDA", PaymentMethod.OTHER, True),
    "IOF de rotativo": ("IOF DE ROTATIVO", PaymentMethod.INTEREST_IOF, False),
    "Juros de rotativo": ("JUROS DE ROTATIVO", PaymentMethod.INTEREST_IOF, False),
    "Juros de dívida encerrada": ("JUROS DE DÍVIDA ENCERRADA", PaymentMethod.INTEREST_IOF, False),
}
_PAYMENT = re.compile(rf"^Pagamento em \d{{2}} {_M}$")
_INTEREST_REFUND = re.compile(r"^Estorno de juros\b")
_PURCHASE_REFUND = re.compile(r'^Estorno de (?:"(?P<loja>.+)"|(?P<loja_nupay>.+?)(?: - NuPay)+)$')
_INTERNATIONAL_IOF = re.compile(r'^IOF de ".+"$')  # IOF charged on a purchase abroad
# start of a description that indicates a financial entry: if it is not one of the known ones, it is an error
_FINANCIAL = re.compile(r"^(?:Juros|IOF|Multa|Encargo|Saldo|Crédito|Estorno|Pagamento|Anuidade|Tarifa|"
                         r"Ajuste|Parcelamento|Encerramento|Financiamento)\b")
_CARD = re.compile(r"^•••• \d{4} ")
_INSTALLMENT = re.compile(r" - Parcela \d+/\d+$")
_NUPAY = " - NuPay"

_METHODS = {normalize_history(h): m for h, m, _ in _FIXED.values()} | {
    normalize_history(h): m for h, m in [
        ("PAGAMENTO DA FATURA", PaymentMethod.INVOICE_PAYMENT),
        ("ESTORNO DE JUROS", PaymentMethod.REFUND),
        ("IOF DE COMPRA INTERNACIONAL", PaymentMethod.INTEREST_IOF),
        ("ESTORNO DE COMPRA", PaymentMethod.REFUND),
        ("COMPRA NO CRÉDITO", PaymentMethod.CREDIT_CARD),
        ("COMPRA PARCELADA", PaymentMethod.CREDIT_CARD),
        ("COMPRA NUPAY", PaymentMethod.CREDIT_CARD),
    ]
}


@dataclass
class _Invoice:
    page: int
    due_date: date
    summary: dict[str, Decimal] = field(default_factory=dict)
    entries: list[tuple[int, date, str, Decimal, int | None]] = field(default_factory=list)
    cardholders: list[tuple[str, Decimal]] = field(default_factory=list)
    section: bool = False
    block: int | None = None  # current cardholder (None = outside a cardholder block)


class NubankInvoicePdf(Parser):
    name = "nubank_fatura_pdf"
    banco = "nubank"
    product = "cartao"
    METHODS = _METHODS
    REJECT_BY_DOCUMENT = True  # each invoice in the file is checked and rejected alone

    @classmethod
    def detect(cls, path: Path) -> bool:
        if path.suffix.lower() != ".pdf":
            return False
        pages = pdf_text(path, 1)
        if not pages:
            return False
        ls = pages[0].splitlines()
        return (len(ls) > 5 and bool(_COVER.match(ls[1])) and any(_DUE_DATE.match(l) for l in ls)
                and any(l.startswith("Limite total do cartão de crédito:") for l in ls))

    def extract(self, path: Path) -> ExtractionResult:
        invoices: list[_Invoice] = []
        holders: set[str] = set()
        for num, text in enumerate(pdf_text(path), start=1):
            ls = text.splitlines()
            if len(ls) > 1 and _COVER.match(ls[1]):
                due = next((m for l in ls if (m := _DUE_DATE.match(l))), None)
                if due is None:
                    raise UnexpectedLayout(self.name, "capa_sem_vencimento", num)
                invoices.append(_Invoice(num, date(int(due["a"]), _MONTHS[due["m"]], int(due["d"]))))
                continue
            if not invoices:
                raise UnexpectedLayout(self.name, "pagina_antes_da_capa", num)
            if len(ls) < 2 or not _HDR_INTERNAL.match(ls[1]):
                raise UnexpectedLayout(self.name, "cabecalho_interno", num)
            holders.add(ls[0].strip())
            self._read_page(ls[2:], num, invoices[-1], holders)
        if not invoices:
            raise UnexpectedLayout(self.name, "sem_faturas")
        return self._result(invoices, sorted(holders))

    def _read_page(self, lines: list[str], num: int, inv: _Invoice, holders: set[str]) -> None:
        if lines and lines[0].startswith("RESUMO DA FATURA"):
            if inv.summary:
                raise UnexpectedLayout(self.name, "dois_resumos", num)
            for l in lines[1:]:
                if l.startswith(_SUMMARY_END):
                    break
                m = _SUMMARY_ITEM.match(l)
                label = m["t"].split(",")[0].lower() if m else ""
                if label not in _SUMMARY:
                    raise UnexpectedLayout(self.name, "item_de_resumo_desconhecido", num)
                inv.summary[label] = -br_amount(m["v"]) if m["s"] else br_amount(m["v"])
            if "total a pagar" not in inv.summary:
                raise UnexpectedLayout(self.name, "resumo_sem_total", num)
            return
        for i, l in enumerate(lines):
            if _SECTION.match(l):
                inv.section = True
                continue
            if not inv.section:
                continue
            if m := _ENTRY.match(l):
                v = br_amount(m["v"])
                inv.entries.append((num, self._date(m["dd"], m["mm"], inv.due_date, num),
                                        m["d"], -v if m["s"] else v, inv.block))
                continue
            if _LOOKS_LIKE_ENTRY.match(l):
                raise UnexpectedLayout(self.name, "lancamento_fora_do_formato", num)
            next_is_entry = i + 1 < len(lines) and bool(_ENTRY.match(lines[i + 1]))
            if next_is_entry and not l.startswith("Pagamentos") and (m := _CARDHOLDER.match(l)):
                inv.cardholders.append((m["nome"].strip(), br_amount(m["v"])))
                holders.add(m["nome"].strip())
                inv.block = len(inv.cardholders) - 1
            elif _PAYMENTS_BLOCK.match(l):
                inv.block = None
            # other lines in the section: explanatory/legal text, no entry

    def _date(self, dd: str, mm: str, due_date: date, num: int) -> date:
        month = _MONTHS[mm]
        year = due_date.year if month <= due_date.month else due_date.year - 1
        try:
            d = date(year, month, int(dd))
        except ValueError:
            raise UnexpectedLayout(self.name, "data", num) from None
        if d > due_date:
            raise UnexpectedLayout(self.name, "lancamento_depois_do_vencimento", num)
        return d

    def _result(self, invoices: list[_Invoice], holders: list[str]) -> ExtractionResult:
        transactions: list[RawTransaction] = []
        segmentos: list[Segment] = []
        seen: set[date] = set()
        for k, f in enumerate(invoices):
            if f.due_date in seen:
                raise UnexpectedLayout(self.name, "fatura_repetida", f.page)
            seen.add(f.due_date)
            if not f.summary:
                raise UnexpectedLayout(self.name, "fatura_sem_resumo", f.page)
            lbl = f"fatura {f.due_date.isoformat()}"
            charges = sum((v for t, v in f.summary.items() if _SUMMARY[t]), Decimal(0))
            i_chg, i_page = len(segmentos), len(segmentos) + 1
            segmentos += [Segment(f"{lbl} cobranças", Decimal(0), -charges, lbl),
                          Segment(f"{lbl} pagamentos", Decimal(0), -f.summary.get("pagamento recebido", Decimal(0)), lbl)]
            i_holder = len(segmentos)
            segmentos += [Segment(f"{lbl} portador {j}", Decimal(0), -sub, lbl) for j, (_, sub) in enumerate(f.cardholders)]
            for num, data, desc, v, block in f.entries:
                historico, contraparte, omitted = self._classify(desc, v)
                if historico == "SALDO RESTANTE DA FATURA ANTERIOR":
                    segs: tuple[int, ...] = ()  # already counted in the original invoice
                elif historico == "PAGAMENTO DA FATURA":
                    segs = (i_page,)
                else:
                    segs = (i_chg,)
                if block is not None:
                    segs += (i_holder + block,)
                # an R$ 0,00 line (e.g. zeroed interest) is not a movement: outside the CSV
                transactions.append(RawTransaction(data, historico, -v, segs, contraparte, page=num,
                                                 omitted=omitted or v == 0))
        return ExtractionResult(self.banco, self.product, transactions, segmentos, holders)

    @staticmethod
    def _classify(desc: str, v: Decimal) -> tuple[str, str, bool]:
        """(history, counterparty, omitted). v is the amount as on the invoice (charge > 0)."""
        if desc in _FIXED:
            h, _, omitted = _FIXED[desc]
            return h, "", omitted
        if _PAYMENT.match(desc):
            return "PAGAMENTO DA FATURA", "", True
        if _INTEREST_REFUND.match(desc):
            return "ESTORNO DE JUROS", "", False
        if _INTERNATIONAL_IOF.match(desc):
            return "IOF DE COMPRA INTERNACIONAL", "", False  # bank tax: no counterparty
        if m := _PURCHASE_REFUND.match(desc):
            return "ESTORNO DE COMPRA", m["loja"] or m["loja_nupay"], False
        if _FINANCIAL.match(desc):
            return desc, "", False  # unknown financial entry: the map rejects the file
        store = _CARD.sub("", desc)
        nupay = store.endswith(_NUPAY)
        if nupay:
            store = store[: -len(_NUPAY)]
        installment = bool(_INSTALLMENT.search(store))
        store = _INSTALLMENT.sub("", store)
        if v < 0:
            return "ESTORNO DE COMPRA", store, False  # purchase credit (cancellation/return)
        return ("COMPRA NUPAY" if nupay else "COMPRA PARCELADA" if installment else "COMPRA NO CRÉDITO"), store, False
