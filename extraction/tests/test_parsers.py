"""Parsers with made-up fixtures (they mimic the layout; no real data)."""

from datetime import date
from decimal import Decimal

import pytest

from statement.cities import split_city
from statement.models import PaymentMethod
from statement.parsers.base import UnexpectedLayout
from statement.parsers.nubank_conta_csv import NubankAccountCsv
from statement.parsers import nubank_common as nu
from statement.pipeline import run

HDR = "Data,Valor,Identificador,Descrição\n"
U1 = "11111111-2222-4333-8444-555555555555"
U2 = "11111111-2222-4333-8444-666666666666"


def _csv(tmp_path, lines):
    p = tmp_path / "extrato.csv"
    p.write_text(HDR + "".join(l + "\n" for l in lines), "utf-8")
    return p


def test_nubank_csv_detects_by_header(tmp_path):
    assert NubankAccountCsv.detect(_csv(tmp_path, []))
    other = tmp_path / "outro.csv"
    other.write_text("Data;Valor\n", "utf-8")
    assert not NubankAccountCsv.detect(other)


def test_nubank_csv_extracts_types_and_counterparties(tmp_path):
    p = _csv(tmp_path, [
        f"02/01/2024,-12.50,{U1},Compra no débito - PADARIA MODELO",
        f'03/01/2024,100.00,{U2},"Transferência recebida pelo Pix - CICLANO DE TESTE - •••.456.789-•• - BCO EXEMPLO S.A. (0999) Agência: 1 Conta: 12345-6"',
    ])
    r = NubankAccountCsv().extract(p)
    a, b = r.transactions
    assert (a.data, a.historico, a.valor, a.contraparte) == (
        date(2024, 1, 2), "Compra no débito", Decimal("-12.50"), "PADARIA MODELO")
    assert (b.historico, b.contraparte, b.counterparty_document) == (
        "Transferência recebida pelo Pix", "CICLANO DE TESTE", "•••.456.789-••")
    assert r.segmentos == [] and NubankAccountCsv.NO_TOTALS


@pytest.mark.parametrize("line,motivo", [
    (f"02/01/2024,12.50,{U1},Compra no débito - PADARIA MODELO", "sinal_incoerente_com_tipo"),
    (f"2024-01-02,-12.50,{U1},Compra no débito - PADARIA MODELO", "data"),
    (f"02/01/2024,-12.5,{U1},Compra no débito - PADARIA MODELO", "valor"),
    ("02/01/2024,-12.50,abc,Compra no débito - PADARIA MODELO", "identificador"),
    (f"02/01/2024,-1.00,{U1},Transferência enviada pelo Pix - CICLANO - BANCO", "transferencia_sem_documento"),
])
def test_nubank_csv_rejects_outside_layout(tmp_path, line, motivo):
    with pytest.raises(UnexpectedLayout) as exc:
        NubankAccountCsv().extract(_csv(tmp_path, [line]))
    assert exc.value.motivo == motivo


def test_nubank_csv_end_to_end(tmp_path):
    source = tmp_path / "raw"
    source.mkdir()
    (source / "x.csv").write_text(HDR + "\n".join([
        f"02/01/2024,-12.50,{U1},Compra no débito - IFOOD *RESTAURANTE FICTICIO",
        f'03/01/2024,-100.00,{U2},"Transferência enviada pelo Pix - CICLANO DE TESTE - •••.456.789-•• - BCO EXEMPLO S.A. (0999) Agência: 1 Conta: 12345-6"',
    ]) + "\n", "utf-8")
    extract_cmd = run(source, "u09", tmp_path / "u09.csv", tmp_path / "privado")
    assert extract_cmd.reports[0].reconciliacao == "sem_totais"
    assert (tmp_path / "u09.csv").read_text("utf-8").splitlines()[1:] == [
        "u09,2024-01-02,COMPRA NO DÉBITO,IFOOD,-12.50,saida,cartao_debito,nubank",
        "u09,2024-01-03,TRANSFERÊNCIA ENVIADA PELO PIX,PESSOA_FISICA,-100.00,saida,pix,nubank",
    ]


def test_nubank_refund_uses_merchant():
    assert nu.contraparte("Estorno", "- Compra no débito - LOJA FICTICIA") == ("LOJA FICTICIA", "")


def test_nubank_map_is_explicit():
    assert nu.METHODS["TRANSFERÊNCIA RECEBIDA"] is PaymentMethod.TED_DOC
    assert "TRANSFERÊNCIA ENVIADA" not in nu.METHODS  # never-seen type: must fail


@pytest.mark.parametrize("text,expected", [
    ("PADARIA FICTICIA CAMPINAS", ("PADARIA FICTICIA", "CAMPINAS")),
    ("POSTO EXEMPLO SAO PAULO", ("POSTO EXEMPLO", "SAO PAULO")),
    ("LOJA FICTICIA SAO JOSE DOS", ("LOJA FICTICIA", "SAO JOSE DOS")),  # truncated at 13
    ("LOJA FICTICIA VILAINVENTADA", None),  # not a municipality
    ("CAMPINAS", None),  # at least one token is left for the merchant
])
def test_split_city(text, expected):
    assert split_city(text, truncated_width=13) == expected


# --- card invoices (classification and year of dates, with made-up descriptions) ---

from statement.parsers.bradesco_cartao_pdf import BradescoCardPdf
from statement.parsers.nubank_fatura_pdf import NubankInvoicePdf
from statement.parsers.santander_cartao_pdf import SantanderCardPdf

D = Decimal


@pytest.mark.parametrize("parser", [BradescoCardPdf, SantanderCardPdf])
@pytest.mark.parametrize("desc,valor,expected", [
    ("LOJA FICTICIA", D("10.00"), ("COMPRA NO CRÉDITO", "LOJA FICTICIA", False)),
    ("LOJA FICTICIA 03/10", D("10.00"), ("COMPRA PARCELADA", "LOJA FICTICIA", False)),
    ("LOJA FICTICIA", D("-10.00"), ("ESTORNO DE COMPRA", "LOJA FICTICIA", False)),
    ("ANUIDADE DIFERENCIADA", D("10.00"), ("ANUIDADE", "", False)),
    ("IOF DIARIO", D("1.00"), ("IOF", "", False)),
])
def test_invoice_classification(parser, desc, valor, expected):
    assert parser._classify(desc, valor) == expected


def test_invoice_payment_stays_out_of_csv():
    assert BradescoCardPdf._classify("PAG BOLETO BANCARIO", D("-100.00"))[2] is True
    assert SantanderCardPdf._classify("PAGAMENTO DE FATURA-INTERNET", D("-100.00"))[2] is True
    assert NubankInvoicePdf._classify("Pagamento em 10 JUL", D("-100.00"))[2] is True


def test_unknown_bank_entry_is_not_purchase():
    # looks like a bank entry and is not in the map: the pipeline rejects it by history
    h, _, _ = SantanderCardPdf._classify("SEGURO FICTICIO", D("5.00"))
    assert h == "SEGURO FICTICIO"


@pytest.mark.parametrize("ddmm,expected", [
    ("20/09", date(2025, 9, 20)),
    ("12/10", date(2024, 10, 12)),  # installment: same month as the due date, but after it -> previous year
    ("15/12", date(2024, 12, 15)),
])
def test_year_of_invoice_date(ddmm, expected):
    due = date(2025, 10, 5)
    assert BradescoCardPdf()._date(ddmm, due, 1) == expected
    assert SantanderCardPdf()._date(ddmm, due, 1) == expected


@pytest.mark.parametrize("line", ["Gerado em: 06/11/2026 - 8h20", "Gerado em: 06/11/2026 - 14h05"])
def test_inter_header_accepts_hour_with_1_or_2_digits(line):
    from statement.parsers.inter_conta_pdf import _HDR
    assert _HDR[0].match(line)


def test_nubank_international_purchase_iof():
    assert NubankInvoicePdf._classify('IOF de "LOJA FICTICIA* ASSINATURA"', D("4.00")) == (
        "IOF DE COMPRA INTERNACIONAL", "", False)
