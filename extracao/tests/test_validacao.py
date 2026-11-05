"""Validador de vazamento: bloqueia a gravação. Dados inventados."""

from datetime import date
from decimal import Decimal

import pytest

from extrato.modelos import LinhaSaida, Meio, Tipo
from extrato.validacao import VazamentoDetectado, grava_csv

TITULARES = ["Fulano de Tal Exemplo"]


def linha(contraparte="", historico="PIX ENVIADO", valor="-10.00"):
    v = Decimal(valor)
    return LinhaSaida(
        id_usuario="u01", data=date(2024, 5, 2), historico=historico, contraparte=contraparte,
        valor=v, tipo=Tipo.ENTRADA if v > 0 else Tipo.SAIDA, meio=Meio.PIX, banco="exemplo",
    )


def test_grava_csv_limpo_no_formato_do_contrato(tmp_path):
    saida = tmp_path / "saida" / "u01.csv"
    grava_csv([linha("PESSOA_FISICA"), linha("PADARIA, MODELO", "COMPRA CARTAO", "25.5")], saida, TITULARES)
    conteudo = saida.read_bytes()
    assert not conteudo.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" not in conteudo
    assert conteudo.decode("utf-8").splitlines() == [
        "id_usuario,data,historico,contraparte,valor,tipo,meio,banco",
        "u01,2024-05-02,PIX ENVIADO,PESSOA_FISICA,-10.00,saida,pix,exemplo",
        'u01,2024-05-02,COMPRA CARTAO,"PADARIA, MODELO",25.50,entrada,pix,exemplo',
    ]


@pytest.mark.parametrize(
    "contraparte,tipo",
    [
        ("LOJA 123.456.789-09", "cpf"),
        ("LOJA •••.456.789-••", "cpf"),
        ("LOJA 12.345.678/0001-90", "cnpj"),
        ("LOJA AG 1234", "agencia_conta"),
        ("LOJA CONTA: 56789-0", "agencia_conta"),
        ("LOJA **** 1234", "cartao"),
        ("LOJA FINAL 1234", "cartao"),
        ("LOJA 1B4E28BA-2FA1-11D2-883F-0016D3CCA427", "chave_pix_aleatoria"),
        ("LOJA@EXEMPLO.COM", "email"),
        ("LOJA (11) 98765-4321", "telefone"),
        ("LOJA RUA DAS FLORES 123", "endereco"),
        ("LOJA 01234-567", "cep"),
        ("LOJA 23790123456000012345678000123456198760000010000", "boleto"),
        ("LOJA 1234567", "codigo_numerico"),
        ("FULANO TAL", "nome_titular"),
        ("FULANO DE TAL EXEMPLO", "nome_titular"),
    ],
)
def test_bloqueia_cada_tipo_de_vazamento(tmp_path, contraparte, tipo):
    saida = tmp_path / "u01.csv"
    with pytest.raises(VazamentoDetectado) as exc:
        grava_csv([linha(), linha(contraparte)], saida, TITULARES)
    assert exc.value.contagem[tipo] == 1
    assert not saida.exists()
    assert list(tmp_path.iterdir()) == []  # nem o temporário fica


def test_mensagem_de_erro_nao_contem_o_dado(tmp_path):
    with pytest.raises(VazamentoDetectado) as exc:
        grava_csv([linha("LOJA 123.456.789-09")], tmp_path / "u01.csv", TITULARES)
    assert "123" not in str(exc.value)


def test_vazamento_preserva_csv_anterior(tmp_path):
    saida = tmp_path / "u01.csv"
    grava_csv([linha()], saida, TITULARES)
    antes = saida.read_bytes()
    with pytest.raises(VazamentoDetectado):
        grava_csv([linha("FULANO TAL")], saida, TITULARES)
    assert saida.read_bytes() == antes
