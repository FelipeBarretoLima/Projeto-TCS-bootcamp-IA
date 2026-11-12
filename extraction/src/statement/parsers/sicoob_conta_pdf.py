"""Sicoob checking account: PDF statement.

Page 1:
    SICOOB / cooperative name (2 lines)
    DD/MM/YYYY EXTRATO CONTA CORRENTE HH:MM:SS
    COOP.: 9999-9 / SICOOB …
    CONTA: 99.999-9 / HOLDER NAME
    PERÍODO: DD/MM/YYYY - DD/MM/YYYY
    DATA DOCUMENTO HISTÓRICO VALOR
The other pages have no header. Entry: "DD/MM/AAAA [DOC] HISTÓRICO 1.234,56C|D",
with the complement on the lines below. Each day closes with "SALDO DO DIA ===== > X C|D".
At the end, a summary starting at "(+) SALDO EM CONTA:".

Reconciliation: one segment per day, previous balance + entries == day balance.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from ..cities import split_city
from ..models import PaymentMethod
from ..normalization import normalize_history, br_amount
from .base import UnexpectedLayout, Parser, ExtractionResult, Segment, RawTransaction, pdf_text

_NUM = r"\d{1,3}(?:\.\d{3})*,\d{2}"
_ENTRY = re.compile(rf"^(?P<data>\d{{2}}/\d{{2}}/\d{{4}}) (?P<texto>.+?) (?P<v>{_NUM})(?P<cd>[CD*])$")
_DAY_BALANCE = re.compile(rf"^SALDO DO DIA ===== > (?P<v>{_NUM})(?P<cd>[CD])$")
_END = "(+) SALDO EM CONTA:"
_FINAL_BALANCE = re.compile(rf"^\(\+\) SALDO EM CONTA: (?P<v>{_NUM})(?P<cd>[CD])$")
_HOLDER = re.compile(r"^CONTA: [\d.]+-\d / (?P<nome>.+)$")
_HEADER = [
    re.compile(r"^SICOOB$"),
    None,  # cooperative name
    None,
    re.compile(r"^\d{2}/\d{2}/\d{4} EXTRATO CONTA CORRENTE \d{2}:\d{2}:\d{2}$"),
    re.compile(r"^COOP\.: \d{4}-\d / SICOOB .+$"),
    _HOLDER,
    re.compile(r"^PERÍODO: \d{2}/\d{2}/\d{4} - \d{2}/\d{2}/\d{4}$"),
    re.compile(r"^DATA DOCUMENTO HISTÓRICO VALOR$"),
]

# history (as Sicoob writes it) -> (method, expected sign: -1, +1 or 0 = any, complement rule)
_TYPES: dict[str, tuple[PaymentMethod, int, str]] = {
    "COMPRA MASTERCARD MAESTRO": (PaymentMethod.DEBIT_CARD, -1, "estabelecimento"),
    "DÉB.TIT.COMPE EFETIVADO": (PaymentMethod.BANK_SLIP, -1, "ignora"),
    "CRÉD.LIQUIDAÇÃO COBRANÇA": (PaymentMethod.BANK_SLIP, +1, "nenhum"),
    "TARIFA COBRANÇA": (PaymentMethod.FEE, -1, "nenhum"),
    "DÉBITO PACOTE SERVIÇOS": (PaymentMethod.FEE, -1, "nenhum"),
    "SAQUE NA AGENCIA": (PaymentMethod.WITHDRAWAL, -1, "ignora"),
    "SAQUE SEM CARTÃO": (PaymentMethod.WITHDRAWAL, -1, "ignora"),
    "DÉBITO SAQUE INTERCREDIS": (PaymentMethod.WITHDRAWAL, -1, "nenhum"),
    "PIX EMITIDO OUTRA IF": (PaymentMethod.PIX, -1, "pix"),
    "PIX EMITIDO OUTRA IF - MESMA TIT.": (PaymentMethod.INTERNAL_TRANSFER, -1, "ignora"),
    "DÉB.TRANSF.CONTAS DIF.TITULARIDADE": (PaymentMethod.TED_DOC, -1, "favorecido"),
    "CRÉD.TRANSF.CONTAS": (PaymentMethod.TED_DOC, +1, "remetente"),
    "DEBITO EMISSÃO TED DIF.TITULARIDADE": (PaymentMethod.TED_DOC, -1, "nome_livre"),
    "TED INTERNET": (PaymentMethod.TED_DOC, 0, "nenhum"),
    "DÉB.CONV.TELECOMUNICAÇÕES": (PaymentMethod.BANK_SLIP, -1, "nenhum"),
    "DÉB.CONV.SANEAMENTO": (PaymentMethod.BANK_SLIP, -1, "nenhum"),
    "DÉB.CONV.EN.ELÉTRICA E GÁS": (PaymentMethod.BANK_SLIP, -1, "nenhum"),
    "DÉB.CONV.ORGÃOS GOV.": (PaymentMethod.BANK_SLIP, -1, "nenhum"),
    "DÉB.CONV.TRIBUTOS FEDERAIS - RFB": (PaymentMethod.BANK_SLIP, -1, "nenhum"),
    "DÉB.CONV.DEMAIS EMPRESAS": (PaymentMethod.BANK_SLIP, -1, "nenhum"),  # company comes first, in the history itself
    "DÉBITO RECARGA PRÉ-PAGA": (PaymentMethod.OTHER, -1, "nenhum"),
    "CRÉD.DISTRIBUIÇÃO SOBRAS/VALORES": (PaymentMethod.YIELD, +1, "nenhum"),
    "ADIANT.DEPOSITANTE": (PaymentMethod.OTHER, 0, "nenhum"),
    "JUROS ADIANT.DEPOSITANTE": (PaymentMethod.INTEREST_IOF, -1, "nenhum"),
    "DÉB.IOF": (PaymentMethod.INTEREST_IOF, -1, "nenhum"),
}
_ORDER = sorted(_TYPES, key=len, reverse=True)
# "SEM PARAR DÉB.CONV.DEMAIS EMPRESAS": the company name comes before the history
_COMPANY_AGREEMENT = re.compile(r"^(?P<empresa>.+?) DÉB\.CONV\.DEMAIS EMPRESAS$")
# document: number, "Pix", "1234ATM", "Recarga" or "IOF/1-2"; may be missing
_DOC = re.compile(r"^(?:\d+|Pix|\d+ATM|Recarga|[A-Z]{3}/\d-\d)$")
_CNPJ_PIX = re.compile(r"^\d{2}\.\d{3}\.\d{3} \d{4}-\d{2}$")
_CPF_PIX = re.compile(r"^\*{3}\.\d{3}\.\d{3}-\*{2}$")


def _cd(valor: Decimal, cd: str) -> Decimal:
    return valor if cd == "C" else -valor


class SicoobAccountPdf(Parser):
    name = "sicoob_conta_pdf"
    banco = "sicoob"
    product = "conta"
    METHODS = {normalize_history(k): v[0] for k, v in _TYPES.items()}

    @classmethod
    def detect(cls, path: Path) -> bool:
        if path.suffix.lower() != ".pdf":
            return False
        pages = pdf_text(path, 1)
        return bool(pages) and cls._header_ok(pages[0].splitlines())

    @staticmethod
    def _header_ok(lines: list[str]) -> bool:
        return len(lines) > len(_HEADER) and all(
            rx is None or rx.match(l) for rx, l in zip(_HEADER, lines)
        )

    def extract(self, path: Path) -> ExtractionResult:
        pages = pdf_text(path)
        first = pages[0].splitlines()
        if not self._header_ok(first):
            raise UnexpectedLayout(self.name, "cabecalho", 1)
        holder = _HOLDER.match(first[5])["nome"].strip()

        # all body lines, with their source page (only for error messages)
        body = [(1, l) for l in first[len(_HEADER):]]
        body += [(n, l) for n, p in enumerate(pages[1:], start=2) for l in p.splitlines()]

        transactions: list[RawTransaction] = []
        segmentos: list[Segment] = []
        balance: Decimal | None = None  # opening balance of the current day
        pending: list | None = None  # [page, date, history, amount, complement[]]
        i = 0
        while i < len(body):
            num, line = body[i]
            i += 1
            if line == "RESUMO" and pending is None:
                continue  # title of the summary block, right before "(+) SALDO EM CONTA:"
            if line.startswith(_END):
                m = _FINAL_BALANCE.match(line)
                if not m or balance is None or _cd(br_amount(m["v"]), m["cd"]) != balance:
                    raise UnexpectedLayout(self.name, "saldo_final_diferente_do_ultimo_saldo_do_dia", num)
                if pending is not None:
                    raise UnexpectedLayout(self.name, "lancamento_sem_saldo_do_dia", num)
                break
            if m := _DAY_BALANCE.match(line):
                if balance is None:
                    raise UnexpectedLayout(self.name, "saldo_do_dia_sem_saldo_anterior", num)
                self._close(pending, transactions, len(segmentos))
                pending = None
                closing = _cd(br_amount(m["v"]), m["cd"])
                segmentos.append(Segment(f"dia {len(segmentos)}", balance, closing))
                balance = closing
                continue
            if m := _ENTRY.match(line):
                text, cd = m["texto"], m["cd"]
                if text == "SALDO ANTERIOR":
                    if balance is not None or cd == "*":
                        raise UnexpectedLayout(self.name, "saldo_anterior", num)
                    balance = _cd(br_amount(m["v"]), cd)
                    continue
                if text == "SALDO BLOQUEADO ANTERIOR" and cd == "*":
                    continue  # informational, not an entry
                if cd == "*" or balance is None:
                    raise UnexpectedLayout(self.name, "lancamento_inesperado", num)
                self._close(pending, transactions, len(segmentos))
                data = datetime.strptime(m["data"], "%d/%m/%Y").date()
                pending = [num, data, text, _cd(br_amount(m["v"]), cd), []]
                continue
            if pending is None:
                raise UnexpectedLayout(self.name, "linha_solta", num)
            pending[4].append(line.strip())
        else:
            raise UnexpectedLayout(self.name, "resumo_final_ausente")

        if not transactions:
            raise UnexpectedLayout(self.name, "arquivo_sem_lancamentos")
        return ExtractionResult(self.banco, self.product, transactions, segmentos, [holder])

    def _close(self, pending: list | None, transactions: list[RawTransaction], segment: int) -> None:
        if pending is None:
            return
        num, data, text, valor, complement = pending
        transactions.append(self._build(num, data, text, valor, complement, segment))

    def _build(self, num: int, data: date, text: str, valor: Decimal, complement: list[str],
               segment: int) -> RawTransaction:
        historico, contraparte = self._split_history(text)
        name = doc = review_note = ""
        if historico in _TYPES:
            _, sign, rule = _TYPES[historico]
            if sign and (valor > 0) != (sign > 0):
                raise UnexpectedLayout(self.name, "sinal_incoerente_com_tipo", num)
            name, doc, review_note = self._complement(rule, complement, num)
            name = name or contraparte
        return RawTransaction(data, historico, valor, segment, name, doc, num, review_note)

    def _split_history(self, text: str) -> tuple[str, str]:
        """(history, embedded company) removing the document from the start."""
        for h in _ORDER:
            if text == h:
                return h, ""
            if text.endswith(" " + h) and _DOC.match(text[: -len(h) - 1]):
                return h, ""
        if m := _COMPANY_AGREEMENT.match(text):
            return "DÉB.CONV.DEMAIS EMPRESAS", m["empresa"]
        first_one, _, rest = text.partition(" ")
        return (rest if rest and _DOC.match(first_one) else text), ""

    def _complement(self, rule: str, lines: list[str], num: int) -> tuple[str, str, str]:
        """(name, document, review reason) according to the type's rule."""
        if rule == "nenhum":
            if lines:
                raise UnexpectedLayout(self.name, "complemento_inesperado", num)
            return "", "", ""
        if rule == "ignora":
            return "", "", ""
        if rule == "estabelecimento":
            if len(lines) != 1 or not lines[0].endswith(" BRA"):
                raise UnexpectedLayout(self.name, "estabelecimento", num)
            text = lines[0][: -len(" BRA")]
            if "*" in text:  # only the prefix before '*' will be used; the city goes along with the rest
                return text.split("*", 1)[0] + "*", "", ""
            split_result = split_city(text, truncated_width=13)
            if split_result is None:
                return "", "", "cidade_nao_identificada"
            return split_result[0], "", ""
        if rule == "pix":
            # "Pagamento Pix" / document / optional free message (ignored)
            if len(lines) < 2 or lines[0] != "Pagamento Pix":
                raise UnexpectedLayout(self.name, "pix", num)
            if _CNPJ_PIX.match(lines[1]):
                return "", lines[1].replace(" ", "/"), ""
            if _CPF_PIX.match(lines[1]) and len(lines) == 2:
                return "", lines[1], ""
            raise UnexpectedLayout(self.name, "pix_documento", num)
        if rule in ("favorecido", "remetente"):
            prefix = "FAV.: " if rule == "favorecido" else "REM.: "
            if not lines or not lines[0].startswith(prefix):
                raise UnexpectedLayout(self.name, rule, num)
            return lines[0][len(prefix):].strip(), "", ""  # other lines: free message, ignored
        if rule == "nome_livre":
            if not lines:
                raise UnexpectedLayout(self.name, "nome_livre", num)
            return " ".join(lines), "", ""
        raise AssertionError(rule)
