"""Training labeling (ml module). Made-up data."""

import csv

import pytest

from statement.models import COLUMNS, INDIVIDUAL_PERSON, PaymentMethod, TransactionType
from ml import label as lbl
from ml.classes import Category, by_rule

S, E = TransactionType.EXPENSE, TransactionType.INCOME


@pytest.mark.parametrize("meio,tipo,historico,contraparte,expected", [
    (PaymentMethod.FEE, S, "TARIFA", "", Category.FINANCIAL),
    (PaymentMethod.INVESTMENT, E, "RESGATE", "", Category.FINANCIAL),
    (PaymentMethod.INVOICE_PAYMENT, S, "PAGAMENTO DE FATURA", "", Category.FINANCIAL),
    (PaymentMethod.SALARY, E, "CREDITO DE SALARIO", "", Category.INCOME),
    (PaymentMethod.PIX, E, "PIX RECEBIDO", INDIVIDUAL_PERSON, Category.INCOME),
    (PaymentMethod.CREDIT_CARD, E, "VALOR ADICIONADO", "", Category.FINANCIAL),
    (PaymentMethod.BANK_SLIP, S, "PAGAMENTO DE BOLETO", INDIVIDUAL_PERSON, Category.BILLS_SERVICES),
    (PaymentMethod.PIX, S, "PIX ENVIADO", INDIVIDUAL_PERSON, Category.PERSON_TRANSFER),
    (PaymentMethod.DEBIT_CARD, S, "COMPRA", INDIVIDUAL_PERSON, Category.PERSON_TRANSFER),
    (PaymentMethod.OTHER, S, "RECARGA DE CELULAR", "", Category.BILLS_SERVICES),
    (PaymentMethod.DEBIT_CARD, S, "COMPRA", "PADARIA MODELO", None),  # depends on the name
    (PaymentMethod.PIX, S, "PIX ENVIADO", "EMPRESA FICTICIA LTDA", None),
])
def test_rules(meio, tipo, historico, contraparte, expected):
    assert by_rule(meio, tipo, historico, contraparte) == expected


def _map(folder, name, rows):
    with open(folder / name, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=lbl.MAP_COLUMNS, lineterminator="\n")
        w.writeheader()
        for l in rows:
            w.writerow({c: l.get(c, "") for c in lbl.MAP_COLUMNS})


def test_map_matches_by_base_name_and_blank_accepts_suggestion(tmp_path):
    _map(tmp_path, lbl.REVIEWED_FILE, [
        {"contraparte": "PADARIA MODELO 12", "classe_sugerida": "mercado", "linhas": "5"},
        {"contraparte": "LOJA X", "classe_sugerida": "compras", "classe": "alimentacao_fora"},
    ])
    _map(tmp_path, lbl.NEW_FILE, [{"contraparte": "POSTO FICTICIO", "classe_sugerida": "transporte"},
                                    {"contraparte": "LOJA X", "classe_sugerida": "mercado"}])  # reviewed wins
    assert lbl.load_map(tmp_path) == {
        "PADARIA MODELO": Category.GROCERIES, "LOJA X": Category.EATING_OUT, "POSTO FICTICIO": Category.TRANSPORT}


def test_invalid_class_in_map_is_error(tmp_path):
    _map(tmp_path, lbl.REVIEWED_FILE, [{"contraparte": "LOJA X", "classe": "comida"}])
    with pytest.raises(ValueError):
        lbl.load_map(tmp_path)


def _parser_csv(path, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(COLUMNS)
        w.writerows(rows)


def test_labeled_is_parser_csv_plus_category(tmp_path):
    source, output, private = tmp_path / "t.csv", tmp_path / "ml" / "r.csv", tmp_path / "privado"
    private.mkdir()
    _map(private, lbl.REVIEWED_FILE, [{"contraparte": "PADARIA MODELO", "classe_sugerida": "mercado"}])
    rows = [
        ["u01", "2024-01-02", "COMPRA NO DÉBITO", "PADARIA MODELO", "-10.00", "saida", "cartao_debito", "nubank"],
        ["u01", "2024-01-03", "TARIFA", "", "-5.00", "saida", "tarifa", "nubank"],
        ["u01", "2024-01-04", "COMPRA NO DÉBITO", "LOJA NUNCA VISTA", "-7.00", "saida", "cartao_debito", "nubank"],
        # PIX to a company arrives without the card standardization: it still matches by base name
        ["u01", "2024-01-05", "PIX ENVIADO", "PADARIA MODELO 12", "-3.00", "saida", "pix", "nubank"],
    ]
    _parser_csv(source, rows)
    res = lbl.label_csv(source, output, private)
    output_rows = list(csv.reader(open(output, encoding="utf-8")))
    assert output_rows[0] == [*COLUMNS, "categoria"]
    assert [l[:-1] for l in output_rows[1:]] == rows  # parser columns intact
    assert [l[-1] for l in output_rows[1:]] == ["mercado", "financeiro", "", "mercado"]
    assert res.new_in_map == 1  # the new store goes into the list to classify
    assert lbl.label_csv(source, output, private).new_in_map == 0  # and is not added again


def test_input_outside_contract_is_error(tmp_path):
    (tmp_path / "t.csv").write_text("a,b\n1,2\n", "utf-8")
    with pytest.raises(ValueError):
        lbl.label_csv(tmp_path / "t.csv", tmp_path / "r.csv", tmp_path)


def test_new_only_appends_and_keeps_filled_rows(tmp_path):
    _map(tmp_path, lbl.REVIEWED_FILE, [{"contraparte": "LOJA JA MAPEADA", "classe_sugerida": "compras"}])
    assert lbl.update_new(tmp_path, ["POSTO FICTICIO", "POSTO FICTICIO", "LOJA JA MAPEADA", INDIVIDUAL_PERSON]) == 1
    rows = list(csv.DictReader(open(tmp_path / lbl.NEW_FILE, encoding="utf-8")))
    assert [(l["contraparte"], l["linhas"], l["classe_sugerida"]) for l in rows] == [("POSTO FICTICIO", "2", "transporte")]
    rows[0]["classe"] = "transporte"
    _map(tmp_path, lbl.NEW_FILE, rows)
    assert lbl.update_new(tmp_path, ["POSTO FICTICIO", "BAR FICTICIO"]) == 1
    after = list(csv.DictReader(open(tmp_path / lbl.NEW_FILE, encoding="utf-8")))
    assert [(l["contraparte"], l["classe"]) for l in after] == [("POSTO FICTICIO", "transporte"), ("BAR FICTICIO", "")]
