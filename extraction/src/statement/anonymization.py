"""Anonymization of a transaction's text fields.

Counterparty rules (deterministic, in order):
  1. CPF and CNPJ together, micro-company suffix (ME, MEI, EPP), name starting with a
     CNPJ root (MEI patterns) or, only in PIX/TED/transfer/bank slip, name with
     8+ consecutive digits (MEI with CPF in the name)                -> ambiguous (review)
     (on cards, a number in the name is the store code: "LOJA.COM 12345678 X" is a company)
  2. CPF (full or masked)                                           -> PESSOA_FISICA,
     unless the name has a company marker                           -> ambiguous
  3. CNPJ or company marker (LTDA, S.A., S/A, EIRELI, CIA)           -> company
  4. No document or marker, in PIX/TED/transfer/bank slip           -> PESSOA_FISICA
     (when in doubt, the fixed token never leaks anything), unless the name does not start with a
     person's first name and has a company word or is a single word -> company
     (`merchants.looks_like_company_by_name`; e.g. "BAR E RESTAURANTE X", "CHEERS",
     "UNIVERSIDADE ESTADUAL DE LONDRINA")
  5. No document or marker, in the other methods (card…)            -> company
Company names go through `patterns.remove` (documents, accounts, holder names…).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from . import patterns
from .merchants import looks_like_company_by_name
from .models import INDIVIDUAL_PERSON, PaymentMethod
from .normalization import normalize_text

_COMPANY = re.compile(r"\b(?:LTDA|EIRELI|CIA|S\.A\.?|S/A|SA)(?=\W|$)")
_MICROCOMPANY = re.compile(r"\b(?:ME|MEI|EPP)\.?$")
_CNPJ_ROOT_AT_START = re.compile(r"^\d{2}[.\s]?\d{3}[.\s]?\d{3}\b")  # "12.345.678 NOME" / "12 345 678 NOME"
_LONG_DIGITS = re.compile(r"\d{8,}")  # "NOME 12345678900": MEI with CPF in the name
_DIGITS_ONLY = re.compile(r"\D")
# a bank slip beneficiary can also be a person (user decision, 2026-11-04)
_TRANSFER_METHODS = {PaymentMethod.PIX, PaymentMethod.TED_DOC, PaymentMethod.INTERNAL_TRANSFER, PaymentMethod.BANK_SLIP}
_CARD_METHODS = {PaymentMethod.DEBIT_CARD, PaymentMethod.CREDIT_CARD}


class PartyClass(StrEnum):
    INDIVIDUAL_PERSON = "pf"
    COMPANY = "pj"
    AMBIGUOUS = "ambiguo"


@dataclass(frozen=True)
class Review:
    """The transaction leaves the CSV and goes to data/privado/revisar.csv."""

    motivo: str  # short code, no statement content


def _has_cpf(text: str) -> bool:
    return bool(patterns.PATTERNS["cpf"].search(text)) or len(_DIGITS_ONLY.sub("", text)) == 11


def _has_cnpj(text: str) -> bool:
    return bool(patterns.PATTERNS["cnpj"].search(text)) or len(_DIGITS_ONLY.sub("", text)) == 14


def classify(name: str, document: str, meio: PaymentMethod) -> PartyClass:
    name_n, doc_n = normalize_text(name), normalize_text(document)
    cpf = _has_cpf(doc_n) if doc_n else bool(patterns.PATTERNS["cpf"].search(name_n))
    cnpj = _has_cnpj(doc_n) if doc_n else bool(patterns.PATTERNS["cnpj"].search(name_n))
    company = bool(_COMPANY.search(name_n))

    mei_with_cpf = meio in _TRANSFER_METHODS and bool(_LONG_DIGITS.search(name_n))
    if (cpf and cnpj) or _MICROCOMPANY.search(name_n) or _CNPJ_ROOT_AT_START.match(name_n) or mei_with_cpf:
        return PartyClass.AMBIGUOUS
    if cpf:
        return PartyClass.AMBIGUOUS if company else PartyClass.INDIVIDUAL_PERSON
    if cnpj or company:
        return PartyClass.COMPANY
    if meio in _TRANSFER_METHODS:
        return PartyClass.COMPANY if looks_like_company_by_name(name_n) else PartyClass.INDIVIDUAL_PERSON
    return PartyClass.COMPANY


# card machine/payment intermediaries: what comes after their name is the seller (often
# a self-employed person). Some banks don't use '*' (e.g. "JIM.COM 12345678 VENDEDOR").
_INTERMEDIARY = re.compile(r"^(JIM\.COM|INFINITEPAY|PAGSEGURO|MERCADOPAGO|SUMUP|PAG|PG|MP|TON|STONE|SAFRAPAY|"
                            r"GETNET|CIELO|PICPAY)\b")


def merchant(name: str) -> str:
    """Card merchant name: only what comes before the first '*'.

    "IFOOD *RESTAURANTE X" -> "IFOOD"; "PAG*FULANO" -> "PAG". What comes after the '*'
    is the sub-merchant (sometimes a person) and only increases cardinality. Known intermediaries
    keep only their own name even without '*': "JIM.COM 12345678 FULANO" -> "JIM.COM".
    The city is not handled here: each parser already delivers the name without it.
    """
    name = name.split("*", 1)[0]
    m = _INTERMEDIARY.match(normalize_text(name))
    return m.group(1) if m else name


def _tidy(text: str) -> str:
    """Removes punctuation leftovers from the removal."""
    text = re.sub(r"\(\s*\)|\[\s*\]", " ", text)
    text = re.sub(r"(?:\s*[-–/|:,;]\s*){2,}", " - ", text)
    return normalize_text(text).strip(" -–/|:,;.")


def anonymize_text(text: str, names: re.Pattern[str] | None) -> str:
    """Removes personal data from free text (history or company name)."""
    return _tidy(patterns.remove(text, names))


def resolve_counterparty(
    name: str, document: str, meio: PaymentMethod, names: re.Pattern[str] | None
) -> str | Review:
    """Final value of the counterparty column, or Review if it cannot be decided safely."""
    if not normalize_text(name) and not normalize_text(document):
        return ""
    party_class = classify(name, document, meio)
    if party_class is PartyClass.INDIVIDUAL_PERSON:
        return INDIVIDUAL_PERSON
    if party_class is PartyClass.AMBIGUOUS:
        return Review("contraparte_ambigua")
    if not normalize_text(name):
        return ""  # company identified only by CNPJ: no name to show
    if names is not None and "nome_titular" in patterns.find(name, names):
        return Review("titular_no_nome_da_empresa")
    if meio in _CARD_METHODS:
        name = merchant(name)
    clean = anonymize_text(name, names)
    if not clean or not re.search(r"[^\W\d_]", clean):
        return Review("empresa_sem_nome_apos_limpeza")
    return clean
