"""Model of the parser's output CSV row (fixed contract).

Contract: id_usuario,data,historico,contraparte,valor,tipo,meio,banco
The category (ML target) is not part of the parser: the `ml` module adds the column.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from .normalization import normalize_history, normalize_text

COLUMNS = ("id_usuario", "data", "historico", "contraparte", "valor", "tipo", "meio", "banco")
INDIVIDUAL_PERSON = "PESSOA_FISICA"


class TransactionType(StrEnum):
    INCOME = "entrada"
    EXPENSE = "saida"


class PaymentMethod(StrEnum):
    PIX = "pix"
    TED_DOC = "ted_doc"
    BANK_SLIP = "boleto"
    DEBIT_CARD = "cartao_debito"
    CREDIT_CARD = "cartao_credito"
    INVOICE_PAYMENT = "pagamento_fatura"
    FEE = "tarifa"
    INTEREST_IOF = "juros_iof"
    INVESTMENT = "investimento"
    YIELD = "rendimento"
    SALARY = "salario"
    WITHDRAWAL = "saque"
    REFUND = "estorno"
    INTERNAL_TRANSFER = "transferencia_interna"
    OTHER = "outros"


class OutputRow(BaseModel):
    """One row of the final CSV. Only built after anonymization."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    id_usuario: str
    data: date
    historico: str
    contraparte: str
    valor: Decimal
    tipo: TransactionType
    meio: PaymentMethod
    banco: str

    @field_validator("id_usuario")
    @classmethod
    def _check_user(cls, v: str) -> str:
        if not re.fullmatch(r"u\d{2}", v):
            raise ValueError("id_usuario deve ser 'u' + 2 dígitos (ex.: u07)")
        return v

    @field_validator("banco")
    @classmethod
    def _check_bank(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", v):
            raise ValueError("banco deve ser slug minúsculo (ex.: bradesco)")
        return v

    @field_validator("historico")
    @classmethod
    def _check_history(cls, v: str) -> str:
        if not v:
            raise ValueError("historico vazio")
        if v != normalize_history(v):
            raise ValueError("historico fora da forma normalizada (maiúsculas, espaços simples, sem dígitos)")
        return v

    @field_validator("contraparte")
    @classmethod
    def _check_counterparty(cls, v: str) -> str:
        if v != normalize_text(v):
            raise ValueError("contraparte fora da forma normalizada (maiúsculas, espaços simples)")
        return v

    @field_validator("valor")
    @classmethod
    def _amount(cls, v: Decimal) -> Decimal:
        if not v.is_finite():
            raise ValueError("valor não finito")
        if v == 0:
            raise ValueError("valor zero não tem tipo definido")
        if v != v.quantize(Decimal("0.01")):
            raise ValueError("valor com mais de 2 casas decimais")
        return v.quantize(Decimal("0.01"))

    @model_validator(mode="after")
    def _check_sign_type(self) -> OutputRow:
        expected = TransactionType.INCOME if self.valor > 0 else TransactionType.EXPENSE
        if self.tipo != expected:
            raise ValueError("tipo incoerente com o sinal do valor")
        return self

    def as_csv_row(self) -> list[str]:
        return [
            self.id_usuario,
            self.data.isoformat(),
            self.historico,
            self.contraparte,
            f"{self.valor:.2f}",
            self.tipo.value,
            self.meio.value,
            self.banco,
        ]
