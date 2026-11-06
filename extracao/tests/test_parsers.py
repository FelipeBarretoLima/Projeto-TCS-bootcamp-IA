"""Parsers com fixtures inventadas (imitam o layout; nenhum dado real)."""

from datetime import date
from decimal import Decimal

import pytest

from extrato.cidades import separa_cidade
from extrato.modelos import Meio
from extrato.parsers.base import LayoutInesperado
from extrato.parsers.nubank_conta_csv import NubankContaCsv
from extrato.parsers import nubank_comum as nu
from extrato.pipeline import executa

CAB = "Data,Valor,Identificador,Descrição\n"
U1 = "11111111-2222-4333-8444-555555555555"
U2 = "11111111-2222-4333-8444-666666666666"


def _csv(tmp_path, linhas):
    p = tmp_path / "extrato.csv"
    p.write_text(CAB + "".join(l + "\n" for l in linhas), "utf-8")
    return p


def test_nubank_csv_detecta_pelo_cabecalho(tmp_path):
    assert NubankContaCsv.detecta(_csv(tmp_path, []))
    outro = tmp_path / "outro.csv"
    outro.write_text("Data;Valor\n", "utf-8")
    assert not NubankContaCsv.detecta(outro)


def test_nubank_csv_extrai_tipos_e_contrapartes(tmp_path):
    p = _csv(tmp_path, [
        f"02/01/2024,-12.50,{U1},Compra no débito - PADARIA MODELO",
        f'03/01/2024,100.00,{U2},"Transferência recebida pelo Pix - CICLANO DE TESTE - •••.456.789-•• - BCO EXEMPLO S.A. (0999) Agência: 1 Conta: 12345-6"',
    ])
    r = NubankContaCsv().extrai(p)
    a, b = r.transacoes
    assert (a.data, a.historico, a.valor, a.contraparte) == (
        date(2024, 1, 2), "Compra no débito", Decimal("-12.50"), "PADARIA MODELO")
    assert (b.historico, b.contraparte, b.documento_contraparte) == (
        "Transferência recebida pelo Pix", "CICLANO DE TESTE", "•••.456.789-••")
    assert r.segmentos == [] and NubankContaCsv.SEM_TOTAIS


@pytest.mark.parametrize("linha,motivo", [
    (f"02/01/2024,12.50,{U1},Compra no débito - PADARIA MODELO", "sinal_incoerente_com_tipo"),
    (f"2024-01-02,-12.50,{U1},Compra no débito - PADARIA MODELO", "data"),
    (f"02/01/2024,-12.5,{U1},Compra no débito - PADARIA MODELO", "valor"),
    ("02/01/2024,-12.50,abc,Compra no débito - PADARIA MODELO", "identificador"),
    (f"02/01/2024,-1.00,{U1},Transferência enviada pelo Pix - CICLANO - BANCO", "transferencia_sem_documento"),
])
def test_nubank_csv_rejeita_fora_do_layout(tmp_path, linha, motivo):
    with pytest.raises(LayoutInesperado) as exc:
        NubankContaCsv().extrai(_csv(tmp_path, [linha]))
    assert exc.value.motivo == motivo


def test_nubank_csv_ponta_a_ponta(tmp_path):
    entrada = tmp_path / "raw"
    entrada.mkdir()
    (entrada / "x.csv").write_text(CAB + "\n".join([
        f"02/01/2024,-12.50,{U1},Compra no débito - IFOOD *RESTAURANTE FICTICIO",
        f'03/01/2024,-100.00,{U2},"Transferência enviada pelo Pix - CICLANO DE TESTE - •••.456.789-•• - BCO EXEMPLO S.A. (0999) Agência: 1 Conta: 12345-6"',
    ]) + "\n", "utf-8")
    ex = executa(entrada, "u09", tmp_path / "u09.csv", tmp_path / "privado")
    assert ex.relatorios[0].reconciliacao == "sem_totais"
    assert (tmp_path / "u09.csv").read_text("utf-8").splitlines()[1:] == [
        "u09,2024-01-02,COMPRA NO DÉBITO,IFOOD,-12.50,saida,cartao_debito,nubank",
        "u09,2024-01-03,TRANSFERÊNCIA ENVIADA PELO PIX,PESSOA_FISICA,-100.00,saida,pix,nubank",
    ]


def test_nubank_estorno_usa_o_estabelecimento():
    assert nu.contraparte("Estorno", "- Compra no débito - LOJA FICTICIA") == ("LOJA FICTICIA", "")


def test_mapa_nubank_e_explicito():
    assert nu.MEIOS["TRANSFERÊNCIA RECEBIDA"] is Meio.TED_DOC
    assert "TRANSFERÊNCIA ENVIADA" not in nu.MEIOS  # tipo nunca visto: tem que dar erro


@pytest.mark.parametrize("texto,esperado", [
    ("PADARIA FICTICIA CAMPINAS", ("PADARIA FICTICIA", "CAMPINAS")),
    ("POSTO EXEMPLO SAO PAULO", ("POSTO EXEMPLO", "SAO PAULO")),
    ("LOJA FICTICIA SAO JOSE DOS", ("LOJA FICTICIA", "SAO JOSE DOS")),  # truncado em 13
    ("LOJA FICTICIA VILAINVENTADA", None),  # não é município
    ("CAMPINAS", None),  # sobra pelo menos um token para o estabelecimento
])
def test_separa_cidade(texto, esperado):
    assert separa_cidade(texto, largura_truncada=13) == esperado


# --- faturas de cartão (classificação e ano das datas, com descrições inventadas) ---

from extrato.parsers.bradesco_cartao_pdf import BradescoCartaoPdf
from extrato.parsers.nubank_fatura_pdf import NubankFaturaPdf
from extrato.parsers.santander_cartao_pdf import SantanderCartaoPdf

D = Decimal


@pytest.mark.parametrize("parser", [BradescoCartaoPdf, SantanderCartaoPdf])
@pytest.mark.parametrize("desc,valor,esperado", [
    ("LOJA FICTICIA", D("10.00"), ("COMPRA NO CRÉDITO", "LOJA FICTICIA", False)),
    ("LOJA FICTICIA 03/10", D("10.00"), ("COMPRA PARCELADA", "LOJA FICTICIA", False)),
    ("LOJA FICTICIA", D("-10.00"), ("ESTORNO DE COMPRA", "LOJA FICTICIA", False)),
    ("ANUIDADE DIFERENCIADA", D("10.00"), ("ANUIDADE", "", False)),
    ("IOF DIARIO", D("1.00"), ("IOF", "", False)),
])
def test_classificacao_das_faturas(parser, desc, valor, esperado):
    assert parser._classifica(desc, valor) == esperado


def test_pagamento_da_fatura_fica_fora_do_csv():
    assert BradescoCartaoPdf._classifica("PAG BOLETO BANCARIO", D("-100.00"))[2] is True
    assert SantanderCartaoPdf._classifica("PAGAMENTO DE FATURA-INTERNET", D("-100.00"))[2] is True
    assert NubankFaturaPdf._classifica("Pagamento em 10 JUL", D("-100.00"))[2] is True


def test_lancamento_do_banco_desconhecido_nao_vira_compra():
    # tem cara de lançamento do banco e não está no mapa: o pipeline rejeita pelo histórico
    h, _, _ = SantanderCartaoPdf._classifica("SEGURO FICTICIO", D("5.00"))
    assert h == "SEGURO FICTICIO"


@pytest.mark.parametrize("ddmm,esperado", [
    ("20/09", date(2025, 9, 20)),
    ("12/10", date(2024, 10, 12)),  # parcela: mesmo mês do vencimento, mas depois dele -> ano anterior
    ("15/12", date(2024, 12, 15)),
])
def test_ano_da_data_da_fatura(ddmm, esperado):
    venc = date(2025, 10, 5)
    assert BradescoCartaoPdf()._data(ddmm, venc, 1) == esperado
    assert SantanderCartaoPdf()._data(ddmm, venc, 1) == esperado


@pytest.mark.parametrize("linha", ["Gerado em: 06/11/2026 - 8h20", "Gerado em: 06/11/2026 - 14h05"])
def test_inter_cabecalho_aceita_hora_com_1_ou_2_digitos(linha):
    from extrato.parsers.inter_conta_pdf import _CAB
    assert _CAB[0].match(linha)


def test_nubank_iof_de_compra_internacional():
    assert NubankFaturaPdf._classifica('IOF de "LOJA FICTICIA* ASSINATURA"', D("4.00")) == (
        "IOF DE COMPRA INTERNACIONAL", "", False)
