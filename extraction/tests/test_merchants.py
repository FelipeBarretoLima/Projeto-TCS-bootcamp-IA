"""Merchant name standardization in the parser. Made-up names."""

import csv

import pytest

from statement import merchants as mer
from statement.models import INDIVIDUAL_PERSON, PaymentMethod


@pytest.mark.parametrize("name,expected", [
    ("PADARIA MODELO 37", "PADARIA MODELO"),
    ("PADARIA MODELO LJ09", "PADARIA MODELO"),
    ("PADARIA MODELO", "PADARIA MODELO"),  # "Modelo" is a municipality (SC), but here it is part of the name
    ("LOJA AMERICANA", "LOJA AMERICANA"),
])
def test_base_name(name, expected):
    assert mer.base_name(name) == expected


@pytest.mark.parametrize("name,expected", [
    ("MARIA DE SOUZA", True),
    ("MARIANASILVEIRA", True),  # glued name
    ("MARIA LANCHES", False),
    ("MARTINS SUPERMERCADO", False),  # business stem inside the word
    ("SANTA LUZIA", False),  # common store name word
    ("LOJA 123", False),
])
def test_looks_like_person(name, expected):
    assert mer.looks_like_person(name) is expected


def test_standardize_only_touches_merchant_purchases():
    assert mer.standardize("PADARIA MODELO 37", PaymentMethod.DEBIT_CARD) == "PADARIA MODELO"
    assert mer.standardize("MARIA DE SOUZA", PaymentMethod.CREDIT_CARD) == INDIVIDUAL_PERSON
    assert mer.standardize("EMPRESA FICTICIA LTDA 37", PaymentMethod.PIX) == "EMPRESA FICTICIA LTDA 37"  # PIX does not change
    assert mer.standardize("", PaymentMethod.DEBIT_CARD) == ""


def test_person_declared_by_user_in_map(tmp_path):
    with open(tmp_path / "estabelecimentos_revisar.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["contraparte", "e_pessoa"])
        w.writeheader()
        w.writerow({"contraparte": "CANTINHO DO ZE 12", "e_pessoa": "sim"})
        w.writerow({"contraparte": "LOJA FICTICIA", "e_pessoa": ""})
    people = mer.declared_people(tmp_path)
    assert people == frozenset({"CANTINHO DO ZE"})
    assert mer.standardize("CANTINHO DO ZE 12", PaymentMethod.DEBIT_CARD, people) == INDIVIDUAL_PERSON
    assert mer.standardize("LOJA FICTICIA", PaymentMethod.DEBIT_CARD, people) == "LOJA FICTICIA"
