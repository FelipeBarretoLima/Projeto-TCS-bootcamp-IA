"""Modelo da linha do CSV de saída do parser (contrato fixo).

Contrato: id_usuario,data,historico,contraparte,valor,tipo,meio,banco
A categoria (target do ML) não faz parte do parser: o módulo `ml` acrescenta a coluna.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from .normalizacao import normaliza_historico, normaliza_texto

COLUNAS = ("id_usuario", "data", "historico", "contraparte", "valor", "tipo", "meio", "banco")
PESSOA_FISICA = "PESSOA_FISICA"


class Tipo(StrEnum):
    ENTRADA = "entrada"
    SAIDA = "saida"


class Meio(StrEnum):
    PIX = "pix"
    TED_DOC = "ted_doc"
    BOLETO = "boleto"
    CARTAO_DEBITO = "cartao_debito"
    CARTAO_CREDITO = "cartao_credito"
    PAGAMENTO_FATURA = "pagamento_fatura"
    TARIFA = "tarifa"
    JUROS_IOF = "juros_iof"
    INVESTIMENTO = "investimento"
    RENDIMENTO = "rendimento"
    SALARIO = "salario"
    SAQUE = "saque"
    ESTORNO = "estorno"
    TRANSFERENCIA_INTERNA = "transferencia_interna"
    OUTROS = "outros"


class LinhaSaida(BaseModel):
    """Uma linha do CSV final. Só é construída depois da anonimização."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    id_usuario: str
    data: date
    historico: str
    contraparte: str
    valor: Decimal
    tipo: Tipo
    meio: Meio
    banco: str

    @field_validator("id_usuario")
    @classmethod
    def _usuario(cls, v: str) -> str:
        if not re.fullmatch(r"u\d{2}", v):
            raise ValueError("id_usuario deve ser 'u' + 2 dígitos (ex.: u07)")
        return v

    @field_validator("banco")
    @classmethod
    def _banco(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", v):
            raise ValueError("banco deve ser slug minúsculo (ex.: bradesco)")
        return v

    @field_validator("historico")
    @classmethod
    def _historico(cls, v: str) -> str:
        if not v:
            raise ValueError("historico vazio")
        if v != normaliza_historico(v):
            raise ValueError("historico fora da forma normalizada (maiúsculas, espaços simples, sem dígitos)")
        return v

    @field_validator("contraparte")
    @classmethod
    def _contraparte(cls, v: str) -> str:
        if v != normaliza_texto(v):
            raise ValueError("contraparte fora da forma normalizada (maiúsculas, espaços simples)")
        return v

    @field_validator("valor")
    @classmethod
    def _valor(cls, v: Decimal) -> Decimal:
        if not v.is_finite():
            raise ValueError("valor não finito")
        if v == 0:
            raise ValueError("valor zero não tem tipo definido")
        if v != v.quantize(Decimal("0.01")):
            raise ValueError("valor com mais de 2 casas decimais")
        return v.quantize(Decimal("0.01"))

    @model_validator(mode="after")
    def _sinal_tipo(self) -> LinhaSaida:
        esperado = Tipo.ENTRADA if self.valor > 0 else Tipo.SAIDA
        if self.tipo != esperado:
            raise ValueError("tipo incoerente com o sinal do valor")
        return self

    def como_linha_csv(self) -> list[str]:
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
