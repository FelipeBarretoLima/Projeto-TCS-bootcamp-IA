"""One case per kind of personal data. All data is made up."""

import pytest

from statement import patterns
from statement.anonymization import PartyClass, Review, anonymize_text, classify, resolve_counterparty
from statement.models import INDIVIDUAL_PERSON, PaymentMethod

HOLDERS = patterns.names_regex(["Fulano de Tal Exemplo", "Beltrana Souza Teste"])


def clean(text):
    return anonymize_text(text, HOLDERS)


@pytest.mark.parametrize(
    "text,expected",
    [
        # full and masked CPF
        ("PADARIA MODELO 123.456.789-09", "PADARIA MODELO"),
        ("PADARIA MODELO •••.456.789-••", "PADARIA MODELO"),
        ("PADARIA MODELO ***.456.789-**", "PADARIA MODELO"),
        # CNPJ
        ("MERCADO FICTICIO LTDA 12.345.678/0001-90", "MERCADO FICTICIO LTDA"),
        # branch and account
        # (the bank's COMPE code, 4 digits, is not personal data and stays)
        ("BANCO FICTICIO S.A. (0999) Agência: 1234 Conta: 56789-0", "BANCO FICTICIO S.A. (0999)"),
        ("BANCO FICTICIO S.A. Ag 1234 C/C 98765", "BANCO FICTICIO S.A"),
        # full card, masked and last digits only
        ("LOJA TESTE 4111 1111 1111 1111", "LOJA TESTE"),
        ("LOJA TESTE 4111 **** **** 1234", "LOJA TESTE"),
        ("LOJA TESTE XXXX.XXXX.XXXX.1234", "LOJA TESTE"),
        ("LOJA TESTE CARTÃO FINAL 1234", "LOJA TESTE CARTÃO"),
        # random PIX key
        ("LOJA TESTE 1b4e28ba-2fa1-11d2-883f-0016d3cca427", "LOJA TESTE"),
        # e-mail (also a PIX key)
        ("LOJA TESTE contato@exemplo.com.br", "LOJA TESTE"),
        # phone (also a PIX key)
        ("LOJA TESTE (11) 98765-4321", "LOJA TESTE"),
        ("LOJA TESTE +55 11 987654321", "LOJA TESTE"),
        # address and CEP
        ("LOJA TESTE RUA DAS FLORES, 123", "LOJA TESTE"),
        ("LOJA TESTE 01234-567", "LOJA TESTE"),
        # bank slip code (typeable line)
        ("COBRANCA 23790.12345 60000.123456 78000.123456 1 98760000010000", "COBRANCA"),
        # document number / long code
        ("LOJA TESTE DOC 1234567", "LOJA TESTE DOC"),
        # holder and cardholder name (full and partial)
        ("TRANSF FULANO DE TAL EXEMPLO", "TRANSF"),
        ("TRANSF FULANO TAL", "TRANSF"),
        ("TRANSF BELTRANA SOUZA", "TRANSF"),
    ],
)
def test_removes_each_personal_data_type(text, expected):
    assert clean(text) == expected
    assert patterns.find(clean(text), HOLDERS) == []


def test_holder_name_with_and_without_accent():
    rx = patterns.names_regex(["José Antônio Teste"])
    assert anonymize_text("PIX JOSE ANTONIO TESTE", rx) == "PIX"
    assert anonymize_text("PIX JOSÉ ANTÔNIO TESTE", rx) == "PIX"


def test_surname_alone_is_not_removed():
    # a loose token appears in company names; only pairs/full names count
    assert clean("SOUZA MATERIAIS LTDA") == "SOUZA MATERIAIS LTDA"


# --- counterparty ---

def test_pix_with_cpf_becomes_individual():
    assert resolve_counterparty("CICLANO EXEMPLO", "•••.456.789-••", PaymentMethod.PIX, HOLDERS) == INDIVIDUAL_PERSON


def test_ted_without_document_becomes_individual():
    assert resolve_counterparty("CICLANO EXEMPLO", "", PaymentMethod.TED_DOC, HOLDERS) == INDIVIDUAL_PERSON


def test_holder_as_pix_counterparty_becomes_individual():
    assert resolve_counterparty("FULANO DE TAL EXEMPLO", "", PaymentMethod.PIX, HOLDERS) == INDIVIDUAL_PERSON


def test_company_with_cnpj_keeps_clean_name():
    r = resolve_counterparty("Mercado Ficticio Ltda", "12.345.678/0001-90", PaymentMethod.PIX, HOLDERS)
    assert r == "MERCADO FICTICIO LTDA"


def test_bank_slip_without_document_or_marker_becomes_individual():
    assert resolve_counterparty("CICLANO EXEMPLO", "", PaymentMethod.BANK_SLIP, HOLDERS) == INDIVIDUAL_PERSON
    assert resolve_counterparty("COMPANHIA FICTICIA S.A.", "", PaymentMethod.BANK_SLIP, HOLDERS) == "COMPANHIA FICTICIA S.A"


def test_card_merchant_keeps_name():
    assert resolve_counterparty("PADARIA MODELO", "", PaymentMethod.DEBIT_CARD, HOLDERS) == "PADARIA MODELO"


def test_numeric_code_in_card_store_is_not_mei():
    # on cards the number is the store code; the cleanup erases the code
    assert resolve_counterparty("LOJAFICTICIA.COM 12345678 OSASCO", "", PaymentMethod.CREDIT_CARD, HOLDERS) == (
        "LOJAFICTICIA.COM OSASCO")
    # but the MEI pattern on cards (CNPJ root + name) still goes to review
    assert isinstance(resolve_counterparty("12345678 JOAO EXEMPLO", "", PaymentMethod.CREDIT_CARD, HOLDERS), Review)


@pytest.mark.parametrize("name,expected", [
    ("JIM.COM 12345678 CICLANOVENDEDOR", "JIM.COM"),  # InfinitePay without '*'
    ("JIM.COM*CICLANO", "JIM.COM"),
    ("PAG*CICLANO EXEMPLO", "PAG"),
    ("MP CICLANO EXEMPLO", "MP"),
    ("PAGODE DO BAIRRO", "PAGODE DO BAIRRO"),  # starts with "PAG" but is not the intermediary
])
def test_card_machine_intermediary_keeps_only_own_name(name, expected):
    assert resolve_counterparty(name, "", PaymentMethod.CREDIT_CARD, HOLDERS) == expected


@pytest.mark.parametrize(
    "name,doc",
    [
        ("JOAO EXEMPLO ME", ""),  # micro-company with a person's name
        ("JOAO EXEMPLO MEI", "12.345.678/0001-90"),
        ("12.345.678 JOAO EXEMPLO", ""),  # MEI pattern: CNPJ root + name
        ("12 345 678 JOAO EXEMPLO", ""),
        ("JOAO EXEMPLO 12345678909", "12.345.678/0001-90"),  # MEI pattern: name + CPF
        ("12345678909", "12.345.678/0001-90"),  # the name is just the CPF
        ("SERVICOS EXEMPLO LTDA", "123.456.789-09"),  # company marker with CPF
    ],
)
def test_ambiguous_cases_go_to_review(name, doc):
    r = resolve_counterparty(name, doc, PaymentMethod.PIX, HOLDERS)
    assert isinstance(r, Review) and r.motivo == "contraparte_ambigua"


def test_company_with_holder_name_goes_to_review():
    r = resolve_counterparty("FULANO TAL LTDA", "12.345.678/0001-90", PaymentMethod.PIX, HOLDERS)
    assert isinstance(r, Review)


def test_without_counterparty_stays_empty():
    assert resolve_counterparty("", "", PaymentMethod.FEE, HOLDERS) == ""


def test_document_classification_beats_method():
    assert classify("ALGUEM", "123.456.789-09", PaymentMethod.DEBIT_CARD) is PartyClass.INDIVIDUAL_PERSON
    assert classify("ALGUMA COISA", "12.345.678/0001-90", PaymentMethod.PIX) is PartyClass.COMPANY


def test_company_with_only_cnpj_has_no_name():
    assert resolve_counterparty("", "12.345.678/0001-90", PaymentMethod.PIX, HOLDERS) == ""


def test_person_with_only_cpf_becomes_individual():
    assert resolve_counterparty("", "***.456.789-**", PaymentMethod.PIX, HOLDERS) == INDIVIDUAL_PERSON


def test_cnpj_with_space_instead_of_slash():
    assert clean("LOJA TESTE 12.345.678 0001-90") == "LOJA TESTE"


# --- PIX/TED to a company without CNPJ or LTDA (legal name written out) ---

@pytest.mark.parametrize("name", [
    "BAR E RESTAURANTE VALENTINO",
    "CIENA COMERCIO DE VESTUARIO",
    "LEROY MERLIN COMPANHIA BRASILEIRA DE BRICOLAGEM",
    "UNIVERSIDADE ESTADUAL DE LONDRINA",
    "CHEERS",                  # a single word that is not a first name
])
def test_pix_to_company_without_cnpj_keeps_name(name):
    assert classify(name, "", PaymentMethod.PIX) is PartyClass.COMPANY
    assert resolve_counterparty(name, "", PaymentMethod.PIX, None) == name


@pytest.mark.parametrize("name", [
    "MARIA SILVA SANTOS",
    "JOAO BARBOSA",            # "BAR" inside the surname is not a company word
    "FREDERICO ALVES",         # "REDE" inside the name
    "JOAO SILVA LANCHES",      # MEI with the owner's name: starts with a first name -> stays protected
    "ANA PAULA COMERCIO",
    "MARIA",                   # a single word, but it is a first name
    "JHONATAN",
])
def test_pix_to_person_stays_individual(name):
    assert resolve_counterparty(name, "", PaymentMethod.PIX, None) == INDIVIDUAL_PERSON
