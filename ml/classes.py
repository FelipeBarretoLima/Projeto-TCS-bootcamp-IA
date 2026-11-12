"""Target classes and deterministic rules (used in labeling and, later, before the model).

Classes (defined with the user on 2026-11-04):
    mercado, alimentacao_fora, transporte, compras, contas_servicos,
    transferencia_pessoa  (PIX/TED to an individual and payment to an individual on a card machine),
    receitas, financeiro

Rules (do not depend on the merchant name): investment/yield/fee/interest/withdrawal/refund/
invoice/own transfer -> financeiro; salary and income -> receitas; paid bank slip ->
contas_servicos; PIX/TED or card to PESSOA_FISICA -> transferencia_pessoa.
What is left (merchant purchase, PIX to a company) depends on the name: map (labeling) or model.
"""

from __future__ import annotations

from enum import StrEnum

from statement.models import INDIVIDUAL_PERSON, PaymentMethod, TransactionType


class Category(StrEnum):
    GROCERIES = "mercado"
    EATING_OUT = "alimentacao_fora"
    TRANSPORT = "transporte"
    SHOPPING = "compras"
    BILLS_SERVICES = "contas_servicos"
    PERSON_TRANSFER = "transferencia_pessoa"
    INCOME = "receitas"
    FINANCIAL = "financeiro"


_FINANCIAL = {PaymentMethod.INVESTMENT, PaymentMethod.YIELD, PaymentMethod.FEE, PaymentMethod.INTEREST_IOF, PaymentMethod.WITHDRAWAL, PaymentMethod.REFUND,
               PaymentMethod.INVOICE_PAYMENT, PaymentMethod.INTERNAL_TRANSFER}


def by_rule(meio: PaymentMethod, tipo: TransactionType, historico: str, contraparte: str) -> Category | None:
    """Category that does not depend on the merchant name (None = depends on the name)."""
    if meio in _FINANCIAL:
        return Category.FINANCIAL
    if meio is PaymentMethod.SALARY:
        return Category.INCOME
    if meio is PaymentMethod.OTHER:
        if tipo is TransactionType.INCOME:
            return Category.INCOME
        return Category.BILLS_SERVICES if "RECARGA" in historico else Category.FINANCIAL
    if tipo is TransactionType.INCOME:
        # card credit moved to the account (Nubank) is a financial movement, not income
        return Category.FINANCIAL if meio is PaymentMethod.CREDIT_CARD else Category.INCOME
    if meio is PaymentMethod.BANK_SLIP:
        return Category.BILLS_SERVICES
    if contraparte == INDIVIDUAL_PERSON:
        return Category.PERSON_TRANSFER
    if meio in (PaymentMethod.PIX, PaymentMethod.TED_DOC) and not contraparte:
        return Category.PERSON_TRANSFER
    return None
