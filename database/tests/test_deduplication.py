"""Rule for not repeating transactions across overlapping statements."""

from datetime import date
from decimal import Decimal

from database.deduplication import split_new, split_new_with_ids


def _t(day=2, amount="-8.94", bank="nubank", counterparty="UBER"):
    return {"banco": bank, "data": date(2024, 1, day), "valor": Decimal(amount), "tipo": "saida",
            "meio": "cartao_credito", "historico": "COMPRA", "contraparte": counterparty}


def test_same_purchase_in_overlapping_statement_goes_in_once():
    to_save, duplicates = split_new([_t()], [_t(), _t(day=3)])
    assert (len(to_save), duplicates) == (1, 1) and to_save[0]["data"].day == 3


def test_genuinely_equal_purchases_go_in_by_count():
    assert split_new([], [_t(), _t()]) == ([_t(), _t()], 0)
    to_save, duplicates = split_new([_t(), _t()], [_t(), _t(), _t()])
    assert (len(to_save), duplicates) == (1, 2)


def test_different_banks_do_not_mix():
    to_save, duplicates = split_new([_t(bank="inter")], [_t(bank="nubank")])
    assert (len(to_save), duplicates) == (1, 0)


def test_amount_compared_in_cents():
    to_save, _ = split_new([_t(amount="-8.9")], [{**_t(), "valor": -8.90}])
    assert to_save == []


def test_duplicates_say_which_saved_transaction_matched():
    existing = [{**_t(), "id": 10}, {**_t(), "id": 11}, {**_t(day=3), "id": 12}]
    to_save, ids = split_new_with_ids(existing, [_t(), _t(day=3), _t(day=4)])
    assert ids == [10, 12] and [t["data"].day for t in to_save] == [4]
