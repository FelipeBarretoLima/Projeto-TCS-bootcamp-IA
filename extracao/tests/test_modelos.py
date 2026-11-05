from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from extrato.modelos import COLUNAS, LinhaSaida, Meio, Tipo


def linha(**kw):
    base = dict(
        id_usuario="u07", data=date(2022, 1, 3), historico="DÉBITO PACOTE SERVIÇOS",
        contraparte="", valor=Decimal("-45.99"), tipo=Tipo.SAIDA, meio=Meio.TARIFA, banco="sicoob",
    )
    base.update(kw)
    return LinhaSaida(**base)


def test_cabecalho_do_contrato():
    assert ",".join(COLUNAS) == "id_usuario,data,historico,contraparte,valor,tipo,meio,banco"


def test_linha_valida_serializa_no_contrato():
    assert linha().como_linha_csv() == [
        "u07", "2022-01-03", "DÉBITO PACOTE SERVIÇOS", "", "-45.99", "saida", "tarifa", "sicoob",
    ]


def test_valor_sempre_com_duas_casas():
    assert linha(valor=Decimal("10"), tipo=Tipo.ENTRADA).como_linha_csv()[4] == "10.00"


@pytest.mark.parametrize("valor,tipo", [(Decimal("-1.00"), Tipo.ENTRADA), (Decimal("1.00"), Tipo.SAIDA)])
def test_tipo_incoerente_com_sinal(valor, tipo):
    with pytest.raises(ValidationError):
        linha(valor=valor, tipo=tipo)


@pytest.mark.parametrize("valor", [Decimal("0"), Decimal("1.234"), Decimal("NaN")])
def test_valor_invalido(valor):
    with pytest.raises(ValidationError):
        linha(valor=valor, tipo=Tipo.ENTRADA)


def test_meio_fora_do_enum():
    with pytest.raises(ValidationError):
        linha(meio="dinheiro")


def test_data_precisa_ser_date():
    with pytest.raises(ValidationError):
        linha(data="03/01/2022")


@pytest.mark.parametrize("usuario", ["7", "u7", "U07", "u007", "joao"])
def test_id_usuario_invalido(usuario):
    with pytest.raises(ValidationError):
        linha(id_usuario=usuario)


@pytest.mark.parametrize("banco", ["Bradesco", "banco inter", "", "nu-bank"])
def test_banco_precisa_ser_slug(banco):
    with pytest.raises(ValidationError):
        linha(banco=banco)


@pytest.mark.parametrize("historico", ["pix enviado", "PIX  ENVIADO", " PIX ENVIADO", "PIX ENVIADO 123456", ""])
def test_historico_fora_da_forma_normalizada(historico):
    with pytest.raises(ValidationError):
        linha(historico=historico)


def test_contraparte_precisa_estar_normalizada():
    with pytest.raises(ValidationError):
        linha(contraparte="Padaria Exemplo")
    assert linha(contraparte="PADARIA EXEMPLO").contraparte == "PADARIA EXEMPLO"


def test_campo_extra_proibido():
    with pytest.raises(ValidationError):
        linha(cpf="123")
