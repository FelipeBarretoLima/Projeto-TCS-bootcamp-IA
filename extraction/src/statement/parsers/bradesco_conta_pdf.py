"""Bradesco checking account: Internet Banking statement in PDF (one or several merged).

Header of every page:
    Bradesco …
    Data: DD/MM/YYYY - HHhMM
    Nome: HOLDER NAME
    Extrato de: Agência: 999 | Conta: 99999-9 Folha: n/N      ("Folha: 1/N" = start of a statement)
    Data Histórico Docto. Crédito (R$) Débito (R$) Saldo (R$)
Table without column text: the parser uses word positions. Each entry has an
anchor line (document, amount, balance) and, 4–5 pt above and below, the history and the complement
(DES:/REM:/merchant). A single-line history, without complement, sits on the anchor itself.
The date only appears on the 1st entry of the day. Last entry of the statement: "Total créditos débitos saldo".

Sign: by column (Crédito/Débito), not by balance. Reconciliation per statement: balance chain
(in stretches, see _balance_stretches)
entry by entry + sum of credits == total + sum of debits == total; and the balance of the
Total == balance of the last entry.

Several statements in the same file: the boundary day between two statements appears in both.
It is only accepted if both copies are identical; the newer statement's copy leaves the CSV (duplicate).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from ..models import PaymentMethod
from ..normalization import normalize_history, br_amount
from .base import UnexpectedLayout, Parser, ExtractionResult, Segment, RawTransaction, pdf_text

_NUM = re.compile(r"^-?\d{1,3}(?:\.\d{3})*,\d{2}-?$")
_DATE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_HDR = [
    re.compile(r"^Bradesco\b.*$"),
    re.compile(r"^Data: \d{2}/\d{2}/\d{4} - \d{2}h\d{2}$"),
    re.compile(r"^Nome: (?P<nome>.+)$"),
    re.compile(r"^Extrato de: Agência: \d+ \| Conta: [\d-]+ Folha: (?P<folha>\d+)/(?P<total>\d+)$"),
    re.compile(r"^Data Histórico Docto\. Crédito \(R\$\) Débito \(R\$\) Saldo \(R\$\)$"),
]
_COLUMN_TOL = 8.0  # pt: numbers are right-aligned to the column
_LINE_TOL = 1.5  # pt: words on the same line
_BAND_TOL = 7.0  # pt: history/complement up to 7 pt from the anchor
_MAX_STRETCH = 15  # entries: longest stretch accepted until the printed balance balances again

# history -> (method, complement rule)
_TYPES: dict[str, tuple[PaymentMethod, str]] = {
    "COMPRA ELO DEBITO VISTA": (PaymentMethod.DEBIT_CARD, "estabelecimento"),
    "COMPRA CARTAO VISA": (PaymentMethod.DEBIT_CARD, "estabelecimento"),
    "COMPRA DEBITO APP ELO": (PaymentMethod.DEBIT_CARD, "estabelecimento"),
    "COMPRA DEBITO APP VISA": (PaymentMethod.DEBIT_CARD, "estabelecimento"),
    "PIX ENVIADO": (PaymentMethod.PIX, "des"),
    "PIX QR CODE DINAMICO": (PaymentMethod.PIX, "des"),
    "PIX QR CODE ESTATICO": (PaymentMethod.PIX, "des"),
    "PIX RECEBIDO": (PaymentMethod.PIX, "rem"),
    "DEVOLUCAO PIX": (PaymentMethod.REFUND, "des_ou_rem"),
    "PAGTO ELETRON COBRANCA": (PaymentMethod.BANK_SLIP, "empresa"),
    "PAGUE FACIL BRADESCO": (PaymentMethod.BANK_SLIP, "empresa"),
    "PAGTO ELETRONICO TRIBUTO": (PaymentMethod.BANK_SLIP, "ignora"),
    "CONTA DE LUZ": (PaymentMethod.BANK_SLIP, "ignora"),
    "TRANSF CC PARA CC": (PaymentMethod.TED_DOC, "empresa"),
    "TED-TRANSF ELET DISPON": (PaymentMethod.TED_DOC, "ignora"),
    "TED C SAL P/ C CORRENTE": (PaymentMethod.SALARY, "ignora"),
    "TRANSF SALDO C/SAL P/CC": (PaymentMethod.SALARY, "ignora"),
    "CREDITO DE SALARIO": (PaymentMethod.SALARY, "ignora"),
    "GASTOS CARTAO DE CREDITO": (PaymentMethod.INVOICE_PAYMENT, "nenhum"),
    "RENTAB.INVEST FACILCRED*": (PaymentMethod.YIELD, "nenhum"),
    "RENDIMENTOS": (PaymentMethod.YIELD, "ignora"),
    "REGULARIZACAORENDIMENTO*": (PaymentMethod.YIELD, "ignora"),
    "RESGATE INVEST FACIL": (PaymentMethod.INVESTMENT, "nenhum"),
    "APLIC.INVEST FACIL": (PaymentMethod.INVESTMENT, "nenhum"),
    "RESG/VENCTO CDB": (PaymentMethod.INVESTMENT, "nenhum"),
    "APLICACAO CDB": (PaymentMethod.INVESTMENT, "nenhum"),
    "BAIXA AUTOMAT POUPANCA*": (PaymentMethod.INTERNAL_TRANSFER, "nenhum"),
    "IOF S/ UTILIZACAO LIMITE": (PaymentMethod.INTEREST_IOF, "nenhum"),
    "ENCARGOS LIMITE DE CRED": (PaymentMethod.INTEREST_IOF, "ignora"),
    "TARIFA BANCARIA": (PaymentMethod.FEE, "ignora"),
    "SAQUE DINHEIRO BANCO 24H": (PaymentMethod.WITHDRAWAL, "ignora"),
    # rare types, mapped with the user on 2026-11-04
    "APLICACAO INVESTIMENTOS": (PaymentMethod.INVESTMENT, "ignora"),
    "APLICACAO LCI": (PaymentMethod.INVESTMENT, "ignora"),
    "SALDO LIQ.INVEST FACIL*": (PaymentMethod.INVESTMENT, "ignora"),
    "CONTA DE TELEFONE": (PaymentMethod.BANK_SLIP, "ignora"),
    "CONTA DE AGUA E ESGOTO": (PaymentMethod.BANK_SLIP, "ignora"),
    "SAQUE DINHEIRO ATM": (PaymentMethod.WITHDRAWAL, "ignora"),
    "TRANSF AG/CONTA": (PaymentMethod.INTERNAL_TRANSFER, "ignora"),
    "TRANSF ENTRE CONTAS": (PaymentMethod.INTERNAL_TRANSFER, "ignora"),
    "TRANSFERENC. DE AGENCIA*": (PaymentMethod.INTERNAL_TRANSFER, "ignora"),
    "TRANSFER SALDO POUPANCA": (PaymentMethod.INTERNAL_TRANSFER, "ignora"),
}
_DES_REM = re.compile(r"^(?P<p>DES|REM): (?P<nome>.*?)(?: \d{2}/\d{2})?$")


@dataclass
class _Line:
    top: float
    words: list[dict]

    def text(self, x_min: float = -1, x_max: float = 1e9) -> str:
        return " ".join(w["text"] for w in self.words if w["x0"] >= x_min and w["x1"] <= x_max)


@dataclass
class _Entry:
    page: int
    data: date
    historico: str
    complement: str
    document: str
    valor: Decimal
    balance: Decimal


@dataclass
class _Statement:
    first_page: int
    sheets: int
    entries: list[_Entry] = field(default_factory=list)
    total: tuple[Decimal, Decimal, Decimal] | None = None  # credits, debits, balance


class BradescoAccountPdf(Parser):
    name = "bradesco_conta_pdf"
    banco = "bradesco"
    product = "conta"
    METHODS = {normalize_history(k): v[0] for k, v in _TYPES.items()}

    @classmethod
    def detect(cls, path: Path) -> bool:
        if path.suffix.lower() != ".pdf":
            return False
        pages = pdf_text(path, 1)
        return bool(pages) and cls._header(pages[0].splitlines()) is not None

    @staticmethod
    def _header(lines: list[str]) -> list[re.Match[str]] | None:
        if len(lines) < len(_HDR):
            return None
        ms = [rx.match(l) for rx, l in zip(_HDR, lines)]
        return ms if all(ms) else None

    # --- reading ---

    def extract(self, path: Path) -> ExtractionResult:
        import pdfplumber

        statements: list[_Statement] = []
        holders: set[str] = set()
        with pdfplumber.open(path) as pdf:
            for num, page in enumerate(pdf.pages, start=1):
                hdr = self._header((page.extract_text() or "").splitlines())
                if hdr is None:
                    raise UnexpectedLayout(self.name, "cabecalho", num)
                holders.add(hdr[2]["nome"].strip())
                sheet, total_sheets = int(hdr[3]["folha"]), int(hdr[3]["total"])
                if sheet == 1:
                    statements.append(_Statement(num, total_sheets))
                elif not statements or sheet != num - statements[-1].first_page + 1 \
                        or total_sheets != statements[-1].sheets:
                    raise UnexpectedLayout(self.name, "folhas_fora_de_sequencia", num)
                if statements[-1].total is not None:
                    raise UnexpectedLayout(self.name, "pagina_depois_do_total", num)
                self._read_page(page, num, statements[-1])
        for e in statements:
            if e.total is None:
                raise UnexpectedLayout(self.name, "extrato_sem_total", e.first_page)
            if not e.entries:
                raise UnexpectedLayout(self.name, "extrato_sem_lancamentos", e.first_page)
        return self._result(statements, sorted(holders))

    def _read_page(self, page, num: int, extrato: _Statement) -> None:
        lines = self._lines(page.extract_words())
        i_hdr = next((i for i, l in enumerate(lines) if l.text().startswith("Data Histórico Docto.")), None)
        if i_hdr is None:
            raise UnexpectedLayout(self.name, "cabecalho_da_tabela", num)
        col = self._columns(lines[i_hdr], num)
        body = lines[i_hdr + 1:]

        def number_in(line: _Line, x1: float) -> list[dict]:
            return [w for w in line.words if _NUM.match(w["text"]) and abs(w["x1"] - x1) <= _COLUMN_TOL]

        anchors = [l for l in body if number_in(l, col["saldo"])]
        used: set[int] = {id(a) for a in anchors}
        current_date = extrato.entries[-1].data if extrato.entries else None

        for a in anchors:
            if extrato.total is not None:
                raise UnexpectedLayout(self.name, "lancamento_depois_do_total", num)
            above = [l for l in body if id(l) not in used and a.top - _BAND_TOL <= l.top < a.top]
            below = [l for l in body if id(l) not in used and a.top < l.top <= a.top + _BAND_TOL]
            used.update(id(l) for l in above + below)
            balance = br_amount(number_in(a, col["saldo"])[0]["text"])
            credit, debit = number_in(a, col["credito"]), number_in(a, col["debito"])

            if a.words[0]["text"] == "Total":
                if above or below or len(credit) != 1 or len(debit) != 1:
                    raise UnexpectedLayout(self.name, "linha_de_total", num)
                extrato.total = (br_amount(credit[0]["text"]), br_amount(debit[0]["text"]), balance)
                continue
            if len(credit) + len(debit) != 1:
                raise UnexpectedLayout(self.name, "valor_em_credito_e_debito", num)
            valor = br_amount((credit or debit)[0]["text"])
            if valor <= 0:
                raise UnexpectedLayout(self.name, "valor_nao_positivo_na_coluna", num)
            valor = valor if credit else -valor

            dates = [w["text"] for w in a.words if w["x1"] <= col["historico"] and _DATE.match(w["text"])]
            if dates:
                current_date = datetime.strptime(dates[0], "%d/%m/%Y").date()
            if current_date is None:
                raise UnexpectedLayout(self.name, "lancamento_sem_data", num)
            document = " ".join(w["text"] for w in a.words
                                 if w["x0"] >= col["docto_ini"] and w["x1"] <= col["docto_fim"])
            band = dict(x_min=col["historico"], x_max=col["docto_ini"])
            if above:
                historico = " ".join(l.text(**band) for l in above)
                complement = " ".join(l.text(**band) for l in below)
            else:
                if below:
                    raise UnexpectedLayout(self.name, "complemento_sem_historico", num)
                historico, complement = a.text(**band), ""
            extrato.entries.append(_Entry(num, current_date, historico, complement, document, valor, balance))

        loose = [l for l in body if id(l) not in used]
        if loose:
            raise UnexpectedLayout(self.name, "linha_fora_de_lancamento", num)

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

    def _columns(self, hdr: _Line, num: int) -> dict[str, float]:
        ws = hdr.words
        texts = [w["text"] for w in ws]
        try:
            i_hist, i_doc = texts.index("Histórico"), texts.index("Docto.")
            i_cred, i_deb, i_bal = texts.index("Crédito"), texts.index("Débito"), texts.index("Saldo")
        except ValueError:
            raise UnexpectedLayout(self.name, "colunas", num) from None
        return {
            "historico": ws[i_hist]["x0"] - 2,
            "docto_ini": ws[i_hist]["x1"] + 100,  # document sits well to the right of the history
            "docto_fim": ws[i_doc]["x1"] + _COLUMN_TOL,
            "credito": ws[i_cred + 1]["x1"],  # "(R$)" right after the column name
            "debito": ws[i_deb + 1]["x1"],
            "saldo": ws[i_bal + 1]["x1"],
        }

    # --- assembly and check ---

    def _result(self, statements: list[_Statement], holders: list[str]) -> ExtractionResult:
        statements = sorted(statements, key=lambda e: e.entries[0].data)
        duplicated = self._boundaries(statements)
        transactions: list[RawTransaction] = []
        segmentos: list[Segment] = []
        for k, e in enumerate(statements):
            credit_total, debit_total, total_balance = e.total
            if e.entries[-1].balance != total_balance:
                raise UnexpectedLayout(self.name, "saldo_do_total_diferente_do_ultimo", e.first_page)
            i_cred, i_deb = len(segmentos), len(segmentos) + 1
            segmentos += [Segment(f"extrato {k} créditos", Decimal(0), credit_total),
                          Segment(f"extrato {k} débitos", Decimal(0), -debit_total)]
            for start, end in self._balance_stretches(e):
                opening = e.entries[start].balance - e.entries[start].valor if start == 0 \
                    else e.entries[start - 1].balance
                segmentos.append(Segment(f"extrato {k} saldo {start}-{end}", opening, e.entries[end].balance))
                for j in range(start, end + 1):
                    l = e.entries[j]
                    t = self._build(l, (len(segmentos) - 1, i_cred if l.valor > 0 else i_deb))
                    transactions.append(replace(t, duplicate=(k, j) in duplicated))
        return ExtractionResult(self.banco, self.product, transactions, segmentos, holders)

    def _balance_stretches(self, e: _Statement) -> list[tuple[int, int]]:
        """Splits the statement into stretches [start, end] that balance by the printed balance.

        Almost always each entry balances on its own (previous balance + amount == balance). At some
        points Bradesco prints intermediate balances that do not follow the entries
        (unlisted automatic movements), but the balance balances again a few lines later:
        the stretch ends at the first entry where it balances. A stretch longer than _MAX_STRETCH,
        or one that does not balance until the end, rejects the file.
        """
        stretches: list[tuple[int, int]] = []
        ls = e.entries
        start, running_sum = 0, Decimal(0)
        opening = ls[0].balance - ls[0].valor
        for j, l in enumerate(ls):
            running_sum += l.valor
            if opening + running_sum == l.balance:
                stretches.append((start, j))
                start, running_sum, opening = j + 1, Decimal(0), l.balance
            elif j - start + 1 > _MAX_STRETCH:
                raise UnexpectedLayout(self.name, "saldo_nao_fecha_em_trecho_curto", l.page)
        if start != len(ls):
            raise UnexpectedLayout(self.name, "saldo_nao_fecha_no_fim_do_extrato", ls[-1].page)
        return stretches

    def _boundaries(self, statements: list[_Statement]) -> set[tuple[int, int]]:
        """(statement, index) of the copies repeated on the boundary day between consecutive statements."""
        key = lambda l: (l.data, l.historico, l.complement, l.document, l.valor, l.balance)
        duplicated: set[tuple[int, int]] = set()
        for k in range(1, len(statements)):
            before, after = statements[k - 1].entries, statements[k].entries
            if before[-1].data < after[0].data:
                continue
            if before[-1].data > after[0].data:
                raise UnexpectedLayout(self.name, "extratos_sobrepostos", statements[k].first_page)
            day = after[0].data
            end = [key(l) for l in before if l.data == day]
            begin = [key(l) for l in after if l.data == day]
            if end != begin:
                raise UnexpectedLayout(self.name, "dia_de_fronteira_diferente", statements[k].first_page)
            duplicated.update((k, j) for j in range(len(begin)))
        return duplicated

    def _build(self, l: _Entry, segs: tuple[int, ...]) -> RawTransaction:
        historico = l.historico
        if historico not in _TYPES:
            return RawTransaction(l.data, historico, l.valor, segs, page=l.page)  # the map rejects it
        rule = _TYPES[historico][1]
        name = ""
        if rule in ("des", "rem", "des_ou_rem"):
            m = _DES_REM.match(l.complement)
            if not m or (rule != "des_ou_rem" and m["p"].lower() != rule) or not m["nome"].strip():
                raise UnexpectedLayout(self.name, f"complemento_{rule}", l.page)
            name = m["nome"].strip()
        elif rule in ("estabelecimento", "empresa"):
            if not l.complement:
                raise UnexpectedLayout(self.name, f"complemento_{rule}", l.page)
            name = l.complement
        elif rule == "nenhum" and l.complement:
            raise UnexpectedLayout(self.name, "complemento_inesperado", l.page)
        return RawTransaction(l.data, historico, l.valor, segs, name, page=l.page)
