"""Regra de não repetir transações entre extratos sobrepostos."""

from datetime import date
from decimal import Decimal

from banco.deduplicacao import separa_novas


def _t(dia=2, valor="-8.94", banco="nubank", contraparte="UBER"):
    return {"banco": banco, "data": date(2024, 1, dia), "valor": Decimal(valor), "tipo": "saida",
            "meio": "cartao_credito", "historico": "COMPRA", "contraparte": contraparte}


def test_mesma_compra_em_extrato_sobreposto_entra_uma_vez():
    gravar, repetidas = separa_novas([_t()], [_t(), _t(dia=3)])
    assert (len(gravar), repetidas) == (1, 1) and gravar[0]["data"].day == 3


def test_compras_iguais_de_verdade_entram_pela_contagem():
    assert separa_novas([], [_t(), _t()]) == ([_t(), _t()], 0)
    gravar, repetidas = separa_novas([_t(), _t()], [_t(), _t(), _t()])
    assert (len(gravar), repetidas) == (1, 2)


def test_bancos_diferentes_nao_se_misturam():
    gravar, repetidas = separa_novas([_t(banco="inter")], [_t(banco="nubank")])
    assert (len(gravar), repetidas) == (1, 0)


def test_valor_comparado_em_centavos():
    gravar, _ = separa_novas([_t(valor="-8.9")], [{**_t(), "valor": -8.90}])
    assert gravar == []
