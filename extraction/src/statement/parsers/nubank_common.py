"""Nubank account vocabulary, shared by the exported CSV and the PDF statement.

Only entry types already seen in statements are included. New type = UnknownHistory.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from ..models import PaymentMethod
from ..normalization import normalize_history

Rule = Literal["transferencia", "estabelecimento", "beneficiario", "estorno", "nenhuma"]


@dataclass(frozen=True)
class NubankType:
    meio: PaymentMethod
    sign: int  # -1 always expense, +1 always income
    contraparte: Rule


# text exactly as Nubank writes it (upper/lower case matters)
TYPES: dict[str, NubankType] = {
    "Transferência enviada pelo Pix": NubankType(PaymentMethod.PIX, -1, "transferencia"),
    "Transferência recebida pelo Pix": NubankType(PaymentMethod.PIX, +1, "transferencia"),
    "Transferência Recebida": NubankType(PaymentMethod.TED_DOC, +1, "transferencia"),
    "Reembolso recebido pelo Pix": NubankType(PaymentMethod.REFUND, +1, "transferencia"),
    "Compra no débito via NuPay": NubankType(PaymentMethod.DEBIT_CARD, -1, "estabelecimento"),
    "Compra no débito": NubankType(PaymentMethod.DEBIT_CARD, -1, "estabelecimento"),
    "Pagamento de boleto efetuado": NubankType(PaymentMethod.BANK_SLIP, -1, "beneficiario"),
    "Depósito Recebido por Boleto": NubankType(PaymentMethod.BANK_SLIP, +1, "nenhuma"),
    "Pagamento de fatura": NubankType(PaymentMethod.INVOICE_PAYMENT, -1, "nenhuma"),
    "Aplicação RDB": NubankType(PaymentMethod.INVESTMENT, -1, "nenhuma"),
    "Resgate RDB": NubankType(PaymentMethod.INVESTMENT, +1, "nenhuma"),
    "Valor adicionado na conta por cartão de crédito": NubankType(PaymentMethod.CREDIT_CARD, +1, "nenhuma"),
    "Recarga de celular": NubankType(PaymentMethod.OTHER, -1, "nenhuma"),
    "Crédito em conta": NubankType(PaymentMethod.OTHER, +1, "nenhuma"),
    "Estorno": NubankType(PaymentMethod.REFUND, +1, "estorno"),
}

METHODS: dict[str, PaymentMethod] = {normalize_history(k): t.meio for k, t in TYPES.items()}

# longest to shortest: "Compra no débito via NuPay" before "Compra no débito"
_ORDER = sorted(TYPES, key=len, reverse=True)

# document as Nubank shows it; in the PDF it may be broken by a space/line
_DOC = (r"(?P<doc>•••\.\s*\d{3}\.\s*\d{3}\s*-\s*••"
        r"|\d{2}\.\s*\d{3}\.\s*\d{3}\s*/\s*\d{4}\s*-\s*\d{2})")
_TRANSFER = re.compile(r"^(?:-\s+)?(?P<nome>.+?)\s+-\s+" + _DOC + r"(?:\s+-\s+.*)?$")
# variant without document or bank, seen in the PDF: "NOME" or "NOME (Transferência enviada)".
# No digit and no " - ": if there were a document/bank, it would fall into the full format above.
_TRANSFER_NAME_ONLY = re.compile(r"^(?P<nome>(?:(?! - )[^()\d])+?)(?: \(Transferência enviada\))?$")

# the fixed complement of "Valor adicionado…" interleaves with the type's line break in the PDF
_PDF_ADDED_AMOUNT = re.compile(
    r"^Valor adicionado na conta por (?:cartão )?Valor adicionado para Pix no Crédito (?:cartão )?de crédito$"
)


def undo_interleaving(text: str) -> str:
    if _PDF_ADDED_AMOUNT.match(text):
        return "Valor adicionado na conta por cartão de crédito - Valor adicionado para Pix no Crédito"
    return text


def split_type(description: str) -> tuple[str, str]:
    """('Compra no débito', 'LOJA X') or (description, '') if the type is not known."""
    for tipo in _ORDER:
        if description == tipo:
            return tipo, ""
        if description.startswith(tipo + " "):
            return tipo, description[len(tipo):].strip()
    return description, ""


class InvalidComplement(ValueError):
    """The complement does not follow the format expected for the type (message without content)."""
    code = "ComplementoInvalido"  # stable code: goes to the report/API


def contraparte(tipo: str, complement: str) -> tuple[str, str]:
    """(name, document) of the counterparty, according to the type's rule."""
    rule = TYPES[tipo].contraparte if tipo in TYPES else "nenhuma"
    rest = re.sub(r"^-\s+", "", complement).strip()
    if rule == "nenhuma":
        return "", ""
    if rule == "transferencia":
        m = _TRANSFER.match(complement)
        if m:
            return m["nome"].strip(), re.sub(r"\s+", "", m["doc"])
        m = _TRANSFER_NAME_ONLY.match(rest)
        if m and tipo == "Transferência enviada pelo Pix":
            return m["nome"].strip(), ""
        raise InvalidComplement("transferencia_sem_documento")
    if rule == "estorno":
        # "Estorno - Compra no débito - LOJA": the merchant is the last part
        sub_type, sub_rest = split_type(rest)
        if sub_type in TYPES:
            rest = re.sub(r"^-\s+", "", sub_rest).strip()
    if not rest:
        raise InvalidComplement(f"{rule}_vazio")
    return rest, ""
