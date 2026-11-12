"""Leak validator: blocks the write. Made-up data."""

from datetime import date
from decimal import Decimal

import pytest

from statement.models import OutputRow, PaymentMethod, TransactionType
from statement.validation import LeakDetected, write_csv

HOLDERS = ["Fulano de Tal Exemplo"]


def line(contraparte="", historico="PIX ENVIADO", valor="-10.00"):
    v = Decimal(valor)
    return OutputRow(
        id_usuario="u01", data=date(2024, 5, 2), historico=historico, contraparte=contraparte,
        valor=v, tipo=TransactionType.INCOME if v > 0 else TransactionType.EXPENSE, meio=PaymentMethod.PIX, banco="exemplo",
    )


def test_write_csv_clean_in_contract_format(tmp_path):
    output = tmp_path / "saida" / "u01.csv"
    write_csv([line("PESSOA_FISICA"), line("PADARIA, MODELO", "COMPRA CARTAO", "25.5")], output, HOLDERS)
    content = output.read_bytes()
    assert not content.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" not in content
    assert content.decode("utf-8").splitlines() == [
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
def test_blocks_each_leak_type(tmp_path, contraparte, tipo):
    output = tmp_path / "u01.csv"
    with pytest.raises(LeakDetected) as exc:
        write_csv([line(), line(contraparte)], output, HOLDERS)
    assert exc.value.counts[tipo] == 1
    assert not output.exists()
    assert list(tmp_path.iterdir()) == []  # not even the temporary file is left


def test_error_message_does_not_contain_data(tmp_path):
    with pytest.raises(LeakDetected) as exc:
        write_csv([line("LOJA 123.456.789-09")], tmp_path / "u01.csv", HOLDERS)
    assert "123" not in str(exc.value)


def test_leak_preserves_previous_csv(tmp_path):
    output = tmp_path / "u01.csv"
    write_csv([line()], output, HOLDERS)
    before = output.read_bytes()
    with pytest.raises(LeakDetected):
        write_csv([line("FULANO TAL")], output, HOLDERS)
    assert output.read_bytes() == before
