"""Padronização do nome de estabelecimento no parser. Nomes inventados."""

import csv

import pytest

from extrato import estabelecimentos as est
from extrato.modelos import PESSOA_FISICA, Meio


@pytest.mark.parametrize("nome,esperado", [
    ("PADARIA MODELO 37", "PADARIA MODELO"),
    ("PADARIA MODELO LJ09", "PADARIA MODELO"),
    ("PADARIA MODELO", "PADARIA MODELO"),  # "Modelo" é município (SC), mas aqui é parte do nome
    ("LOJA AMERICANA", "LOJA AMERICANA"),
])
def test_nome_base(nome, esperado):
    assert est.nome_base(nome) == esperado


@pytest.mark.parametrize("nome,esperado", [
    ("MARIA DE SOUZA", True),
    ("MARIANASILVEIRA", True),  # nome colado
    ("MARIA LANCHES", False),
    ("MARTINS SUPERMERCADO", False),  # radical de ramo dentro da palavra
    ("SANTA LUZIA", False),  # palavra comum de nome de loja
    ("LOJA 123", False),
])
def test_parece_pessoa(nome, esperado):
    assert est.parece_pessoa(nome) is esperado


def test_padroniza_so_mexe_em_compra_de_estabelecimento():
    assert est.padroniza("PADARIA MODELO 37", Meio.CARTAO_DEBITO) == "PADARIA MODELO"
    assert est.padroniza("MARIA DE SOUZA", Meio.CARTAO_CREDITO) == PESSOA_FISICA
    assert est.padroniza("EMPRESA FICTICIA LTDA 37", Meio.PIX) == "EMPRESA FICTICIA LTDA 37"  # PIX não muda
    assert est.padroniza("", Meio.CARTAO_DEBITO) == ""


def test_pessoa_declarada_pelo_usuario_no_mapa(tmp_path):
    with open(tmp_path / "estabelecimentos_revisar.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["contraparte", "e_pessoa"])
        w.writeheader()
        w.writerow({"contraparte": "CANTINHO DO ZE 12", "e_pessoa": "sim"})
        w.writerow({"contraparte": "LOJA FICTICIA", "e_pessoa": ""})
    pessoas = est.pessoas_declaradas(tmp_path)
    assert pessoas == frozenset({"CANTINHO DO ZE"})
    assert est.padroniza("CANTINHO DO ZE 12", Meio.CARTAO_DEBITO, pessoas) == PESSOA_FISICA
    assert est.padroniza("LOJA FICTICIA", Meio.CARTAO_DEBITO, pessoas) == "LOJA FICTICIA"
