from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from statement.models import COLUMNS, OutputRow, PaymentMethod, TransactionType


def line(**kw):
    base = dict(
        id_usuario="u07", data=date(2022, 1, 3), historico="DÉBITO PACOTE SERVIÇOS",
        contraparte="", valor=Decimal("-45.99"), tipo=TransactionType.EXPENSE, meio=PaymentMethod.FEE, banco="sicoob",
    )
    base.update(kw)
    return OutputRow(**base)


def test_contract_header():
    assert ",".join(COLUMNS) == "id_usuario,data,historico,contraparte,valor,tipo,meio,banco"


def test_valid_row_serializes_to_contract():
    assert line().as_csv_row() == [
        "u07", "2022-01-03", "DÉBITO PACOTE SERVIÇOS", "", "-45.99", "saida", "tarifa", "sicoob",
    ]


def test_amount_always_two_decimals():
    assert line(valor=Decimal("10"), tipo=TransactionType.INCOME).as_csv_row()[4] == "10.00"


@pytest.mark.parametrize("valor,tipo", [(Decimal("-1.00"), TransactionType.INCOME), (Decimal("1.00"), TransactionType.EXPENSE)])
def test_type_inconsistent_with_sign(valor, tipo):
    with pytest.raises(ValidationError):
        line(valor=valor, tipo=tipo)


@pytest.mark.parametrize("valor", [Decimal("0"), Decimal("1.234"), Decimal("NaN")])
def test_invalid_amount(valor):
    with pytest.raises(ValidationError):
        line(valor=valor, tipo=TransactionType.INCOME)


def test_method_outside_enum():
    with pytest.raises(ValidationError):
        line(meio="dinheiro")


def test_date_must_be_date():
    with pytest.raises(ValidationError):
        line(data="03/01/2022")


@pytest.mark.parametrize("user", ["7", "u7", "U07", "u007", "joao"])
def test_invalid_user_id(user):
    with pytest.raises(ValidationError):
        line(id_usuario=user)


@pytest.mark.parametrize("banco", ["Bradesco", "banco inter", "", "nu-bank"])
def test_bank_must_be_slug(banco):
    with pytest.raises(ValidationError):
        line(banco=banco)


@pytest.mark.parametrize("historico", ["pix enviado", "PIX  ENVIADO", " PIX ENVIADO", "PIX ENVIADO 123456", ""])
def test_history_not_normalized(historico):
    with pytest.raises(ValidationError):
        line(historico=historico)


def test_counterparty_must_be_normalized():
    with pytest.raises(ValidationError):
        line(contraparte="Padaria Exemplo")
    assert line(contraparte="PADARIA EXEMPLO").contraparte == "PADARIA EXEMPLO"


def test_extra_field_forbidden():
    with pytest.raises(ValidationError):
        line(cpf="123")
