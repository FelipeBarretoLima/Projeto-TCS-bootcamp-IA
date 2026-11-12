"""Inter account: PDF statement.

Page 1:
    Gerado em: DD/MM/YYYY - HHhMM
    HOLDER NAME
    CPF/CNPJ: …, Instituição: Banco Inter, Agência: …, Conta: …
    Período: DD/MM/YYYY a DD/MM/YYYY
    Saldo total Saldo disponível: Saldo bloqueado:
    R$ X R$ Y R$ Z
    (blocked + available)
Body (all pages): "D de Mês de AAAA Saldo do dia: R$ X" and entries
    Type: "complement" ±R$ amount R$ balance_after
The quoted complement may continue on the next line. Footer: "Fale com a gente" and "SAC: …".

Reconciliation: each entry is a segment (previous balance + amount == balance after).
The opening balance of the 1st entry is not printed: it is derived from the entry itself, so the 1st
amount is only checked by the layout checks: "Saldo do dia" == balance of the day's last entry
and the summary's "Saldo total" == balance of the last entry.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from ..models import PaymentMethod
from ..normalization import normalize_history, br_amount
from .base import UnexpectedLayout, Parser, ExtractionResult, Segment, RawTransaction, pdf_text

_MONTHS = {m: i for i, m in enumerate(
    "Janeiro Fevereiro Março Abril Maio Junho Julho Agosto Setembro Outubro Novembro Dezembro".split(), start=1)}
_V = r"-?R\$ -?\d{1,3}(?:\.\d{3})*,\d{2}"
_HDR = [
    re.compile(r"^\S+ em: \d{2}/\d{2}/\d{4} - \d{1,2}h\d{2}$"),  # hour with 1 or 2 digits ("8h20", "14h05")
    None,  # holder name
    re.compile(r"^CPF/CNPJ: .+, Instituição: Banco Inter, Agência: [\d-]+, Conta: [\d-]+$"),
    re.compile(r"^Período: \d{2}/\d{2}/\d{4} a \d{2}/\d{2}/\d{4}$"),
    re.compile(r"^Saldo total Saldo disponível: Saldo bloqueado:$"),
    re.compile(rf"^(?P<total>{_V}) (?P<disp>{_V}) (?P<bloq>{_V})$"),
    re.compile(r"^\(bloqueado \+ disponível\)$"),
]
_DAY = re.compile(rf"^(?P<d>\d{{1,2}}) de (?P<m>{'|'.join(_MONTHS)}) de (?P<a>\d{{4}}) "
                  rf"Saldo do dia: (?P<s>{_V})(?: Valor Saldo por transação)?$")
_TYPES: dict[str, tuple[PaymentMethod, int, bool]] = {  # type -> (method, sign, has counterparty)
    "Pix enviado": (PaymentMethod.PIX, -1, True),
    "Pix recebido": (PaymentMethod.PIX, +1, True),
    "Pix enviado devolvido": (PaymentMethod.REFUND, +1, True),
    "Pix recebido devolvido": (PaymentMethod.REFUND, -1, True),
    "Resgate": (PaymentMethod.INVESTMENT, +1, False),
    "Aplicacao": (PaymentMethod.INVESTMENT, -1, False),
}
_ENTRY = re.compile(rf'^(?P<tipo>[^:"]+): (?P<q>".*?) (?P<v>{_V}) (?P<s>{_V})$')
_FOOTER = re.compile(r"^(?:Fale com a gente|SAC: .*Ouvidoria: .*)$")
# quoted content
_PIX_ISPB = re.compile(r"^Cp :\d{8}-(?P<nome>.+)$")
_PIX_BRANCH_ACCOUNT = re.compile(r"^\d{5} \d{8,9} (?P<nome>.+)$")
_INVESTMENT = re.compile(r"^CDB POS DI LIQ\. BANCO INTER S ?A$")


class InterAccountPdf(Parser):
    name = "inter_conta_pdf"
    banco = "inter"
    product = "conta"
    METHODS = {normalize_history(k): v[0] for k, v in _TYPES.items()}

    @classmethod
    def detect(cls, path: Path) -> bool:
        if path.suffix.lower() != ".pdf":
            return False
        pages = pdf_text(path, 1)
        return bool(pages) and cls._header(pages[0].splitlines()) is not None

    @staticmethod
    def _header(lines: list[str]) -> re.Match[str] | None:
        if len(lines) <= len(_HDR) or not all(rx is None or rx.match(l) for rx, l in zip(_HDR, lines)):
            return None
        return _HDR[5].match(lines[5])

    def extract(self, path: Path) -> ExtractionResult:
        pages = pdf_text(path)
        first = pages[0].splitlines()
        summary = self._header(first)
        if summary is None:
            raise UnexpectedLayout(self.name, "cabecalho", 1)
        holder = first[1].strip()
        body = [(1, l) for l in first[len(_HDR):]]
        body += [(n, l) for n, p in enumerate(pages[1:], start=2) for l in p.splitlines()]

        transactions: list[RawTransaction] = []
        segmentos: list[Segment] = []
        day: date | None = None
        day_balance: Decimal | None = None
        balance: Decimal | None = None
        pending: list | None = None  # [page, date, type, quotes, amount] with quotes still open

        def check_day(num: int) -> None:
            if day_balance is not None and balance != day_balance:
                raise UnexpectedLayout(self.name, "saldo_do_dia_diferente_do_ultimo_lancamento", num)

        for num, line in body:
            if pending is not None:  # quoted complement continues on this line
                if not line.endswith('"') or '"' in line[:-1]:
                    raise UnexpectedLayout(self.name, "aspas_nao_fechadas", num)
                pending[3] += " " + line
                transactions.append(self._build(*pending, len(segmentos) - 1))
                pending = None
                continue
            if _FOOTER.match(line):
                continue
            if m := _DAY.match(line):
                check_day(num)
                day = date(int(m["a"]), _MONTHS[m["m"]], int(m["d"]))
                day_balance = br_amount(m["s"])
                continue
            if m := _ENTRY.match(line):
                if day is None:
                    raise UnexpectedLayout(self.name, "lancamento_sem_dia", num)
                valor, following = br_amount(m["v"]), br_amount(m["s"])
                segmentos.append(Segment(f"lançamento {len(segmentos)}",
                                          following - valor if balance is None else balance, following))
                balance = following
                item = [num, day, m["tipo"], m["q"], valor]
                if m["q"].count('"') == 1:
                    pending = item
                else:
                    transactions.append(self._build(*item, len(segmentos) - 1))
                continue
            raise UnexpectedLayout(self.name, "linha_desconhecida", num)
        if pending is not None:
            raise UnexpectedLayout(self.name, "aspas_nao_fechadas", len(pages))
        check_day(len(pages))
        if not transactions:
            raise UnexpectedLayout(self.name, "arquivo_sem_lancamentos")
        if br_amount(summary["total"]) != balance:
            raise UnexpectedLayout(self.name, "saldo_total_diferente_do_ultimo_lancamento", 1)
        return ExtractionResult(self.banco, self.product, transactions, segmentos, [holder])

    def _build(self, num: int, day: date, tipo: str, quotes: str, valor: Decimal, segment: int) -> RawTransaction:
        if not (quotes.startswith('"') and quotes.endswith('"') and quotes.count('"') == 2):
            raise UnexpectedLayout(self.name, "complemento_sem_aspas", num)
        content = quotes[1:-1].strip()
        if tipo not in _TYPES:
            return RawTransaction(day, tipo, valor, segment, page=num)  # the map rejects it later
        _, sign, has_counterparty = _TYPES[tipo]
        if (valor > 0) != (sign > 0):
            raise UnexpectedLayout(self.name, "sinal_incoerente_com_tipo", num)
        if not has_counterparty:
            if not _INVESTMENT.match(content):
                raise UnexpectedLayout(self.name, "produto_de_investimento", num)
            return RawTransaction(day, tipo, valor, segment, page=num)
        m = _PIX_ISPB.match(content) or _PIX_BRANCH_ACCOUNT.match(content)
        if not m:
            raise UnexpectedLayout(self.name, "complemento_pix", num)
        return RawTransaction(day, tipo, valor, segment, m["nome"].strip(), page=num)
