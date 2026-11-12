"""Registry, reconciliation and end-to-end pipeline with a fake parser."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from statement.models import PaymentMethod
from statement.normalization import normalize_history, br_amount
from statement.parsers.base import (
    AmbiguousFormat, UnrecognizedFormat, Parser, ExtractionResult, Segment, RawTransaction,
)
from statement.parsers.registry import choose_parser
from statement.pipeline import run
from statement.reconciliation import ReconciliationFailed, reconcile

D = Decimal


class ParserFake(Parser):
    """Reads a made-up .fake: 'saldo_inicial;saldo_final' and then 'AAAA-MM-DD;historico;valor;nome;doc'."""

    name, banco, product = "fake_conta", "fakebank", "conta"
    METHODS = {"PIX ENVIADO": PaymentMethod.PIX, "PIX RECEBIDO": PaymentMethod.PIX, "COMPRA DEBITO": PaymentMethod.DEBIT_CARD,
             "TARIFA": PaymentMethod.FEE}

    @classmethod
    def detect(cls, path):
        return path.suffix == ".fake"

    def extract(self, path):
        lines = path.read_text("utf-8").splitlines()
        begin, end = (D(x) for x in lines[0].split(";"))
        txs = []
        for l in lines[1:]:
            d, h, v, n, doc = l.split(";")
            txs.append(RawTransaction(date.fromisoformat(d), h, D(v), 0, n, doc))
        return ExtractionResult(self.banco, self.product, txs, [Segment("arquivo", begin, end)],
                                 holder_names=["Fulano de Tal Exemplo"])


class OtherFake(ParserFake):
    name = "outro_fake"


# --- registry ---

def test_no_parser_recognizes(tmp_path):
    with pytest.raises(UnrecognizedFormat):
        choose_parser(tmp_path / "x.pdf", [ParserFake])


def test_more_than_one_parser_recognizes(tmp_path):
    with pytest.raises(AmbiguousFormat):
        choose_parser(tmp_path / "x.fake", [ParserFake, OtherFake])


def test_exactly_one_parser(tmp_path):
    assert isinstance(choose_parser(tmp_path / "x.fake", [ParserFake]), ParserFake)


# --- reconciliation ---

def _res(amounts, opening, closing):
    txs = [RawTransaction(date(2024, 1, 1), "TARIFA", D(v), 0) for v in amounts]
    return ExtractionResult("x", "conta", txs, [Segment("s", D(opening), D(closing))])


def test_reconciliation_ok():
    assert reconcile(_res(["-10.00", "5.50"], "100.00", "95.50")).ok


def test_reconciliation_fails_by_one_cent():
    with pytest.raises(ReconciliationFailed):
        reconcile(_res(["-10.00", "5.50"], "100.00", "95.49"))


def test_reconciliation_without_totals_rejects():
    with pytest.raises(ReconciliationFailed):
        reconcile(ExtractionResult("x", "conta", [], []))


def test_document_rejection_removes_only_unbalanced_document():
    from statement.reconciliation import split_divergent_documents
    txs = [RawTransaction(date(2024, 1, 1), "TARIFA", D("-1.00"), (0,)),
           RawTransaction(date(2024, 2, 1), "TARIFA", D("-2.00"), (1,)),
           RawTransaction(date(2024, 2, 2), "TARIFA", D("-3.00"), (1, 2))]
    segs = [Segment("a", D(0), D("-1.00"), "fatura A"),
            Segment("b", D(0), D("-9.00"), "fatura B"),  # does not balance
            Segment("b2", D(0), D("-3.00"), "fatura B")]
    r, bad = split_divergent_documents(ExtractionResult("x", "cartao", txs, segs))
    assert bad == ["fatura B"]
    assert [t.valor for t in r.transactions] == [D("-1.00")]
    assert reconcile(r).ok


def test_document_rejection_requires_document_label():
    from statement.reconciliation import split_divergent_documents
    with pytest.raises(ReconciliationFailed):
        split_divergent_documents(_res(["-1.00"], "0.00", "-1.00"))


def test_transaction_in_missing_segment_rejects():
    r = _res(["-1.00"], "1.00", "0.00")
    r.transactions.append(RawTransaction(date(2024, 1, 1), "TARIFA", D("0.00"), 5))
    with pytest.raises(ReconciliationFailed):
        reconcile(r)


# --- normalization ---

def test_normalize_history():
    assert normalize_history("  Pix   enviado - 123456 ") == "PIX ENVIADO"


@pytest.mark.parametrize("txt,expected", [
    ("1.234,56", "1234.56"), ("R$ 1.234,56", "1234.56"), ("-R$ 1,00", "-1.00"),
    ("R$ -1,00", "-1.00"), ("999,99-", "-999.99"), ("+0,10", "0.10"),
])
def test_br_amount(txt, expected):
    assert br_amount(txt) == D(expected)


@pytest.mark.parametrize("txt", ["1,2", "abc", "-1,00-", "1.23,45"])
def test_invalid_br_amount(txt):
    with pytest.raises(ValueError):
        br_amount(txt)


# --- end to end ---

def _write(folder: Path, name: str, content: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(content, "utf-8")


def test_pipeline_end_to_end(tmp_path):
    source = tmp_path / "raw"
    _write(source, "a.fake", "\n".join([
        "100.00;64.50",
        "2024-01-02;Pix enviado;-20.00;CICLANO EXEMPLO;•••.456.789-••",
        "2024-01-03;COMPRA DEBITO;-10.50;PADARIA MODELO 12.345.678/0001-90;",
        "2024-01-04;PIX RECEBIDO;5.00;JOAO EXEMPLO ME;",  # ambiguous -> review
        "2024-01-05;TARIFA;-10.00;;",
    ]))
    output, private = tmp_path / "saida" / "u07.csv", tmp_path / "privado"
    extract_cmd = run(source, "u07", output, private, [ParserFake])

    assert extract_cmd.exit_code == 0
    assert output.read_text("utf-8").splitlines() == [
        "id_usuario,data,historico,contraparte,valor,tipo,meio,banco",
        "u07,2024-01-02,PIX ENVIADO,PESSOA_FISICA,-20.00,saida,pix,fakebank",
        "u07,2024-01-03,COMPRA DEBITO,PADARIA MODELO,-10.50,saida,cartao_debito,fakebank",
        "u07,2024-01-05,TARIFA,,-10.00,saida,tarifa,fakebank",
    ]
    rel = extract_cmd.reports[0]
    assert (rel.status, rel.reconciliacao, rel.linhas_extraidas, rel.linhas_gravadas, rel.linhas_revisar) == (
        "aceito", "ok", 4, 3, 1)
    assert (private / "revisar.csv").exists()
    assert (output.parent / "u07.relatorio.csv").exists()


def test_originals_follow_rows_and_stay_out_of_csv(tmp_path):
    source = tmp_path / "raw"
    _write(source, "a.fake", "\n".join([
        "100.00;64.50",
        "2024-01-02;Pix enviado;-20.00;CICLANO EXEMPLO;•••.456.789-••",
        "2024-01-03;COMPRA DEBITO;-10.50;PADARIA MODELO 12.345.678/0001-90;",
        "2024-01-04;PIX RECEBIDO;5.00;JOAO EXEMPLO ME;",  # ambiguous -> review: no row, no original
        "2024-01-05;TARIFA;-10.00;;",
    ]))
    output = tmp_path / "saida" / "u07.csv"
    extract_cmd = run(source, "u07", output, tmp_path / "privado", [ParserFake])
    # one original per row, in the same order; the document (CPF/CNPJ) is not part of the original
    assert [(l.contraparte, o["contraparte"]) for l, o in zip(extract_cmd.lines, extract_cmd.originals, strict=True)] == [
        ("PESSOA_FISICA", "CICLANO EXEMPLO"),
        ("PADARIA MODELO", "PADARIA MODELO 12.345.678/0001-90"),
        ("", ""),
    ]
    assert [o["historico"] for o in extract_cmd.originals] == ["PIX ENVIADO", "COMPRA DEBITO", "TARIFA"]
    assert "CICLANO" not in output.read_text("utf-8")  # the training CSV stays anonymized


def test_unknown_history_rejects_file(tmp_path):
    source = tmp_path / "raw"
    _write(source, "a.fake", "0.00;-1.00\n2024-01-02;LANCAMENTO NOVO;-1.00;;")
    extract_cmd = run(source, "u07", tmp_path / "u07.csv", tmp_path / "privado", [ParserFake])
    assert extract_cmd.exit_code == 1
    assert extract_cmd.reports[0].motivo == "HistoricoDesconhecido"
    assert not (tmp_path / "u07.csv").exists()
    assert "LANCAMENTO NOVO" in (tmp_path / "privado" / "historicos_desconhecidos.csv").read_text("utf-8")


def test_divergent_reconciliation_rejects_and_accepts_rest(tmp_path):
    source = tmp_path / "raw"
    _write(source, "ruim.fake", "0.00;-2.00\n2024-01-02;TARIFA;-1.00;;")
    _write(source, "bom.fake", "0.00;-1.00\n2024-01-02;TARIFA;-1.00;;")
    _write(source, "x.pdf", "nao e pdf")
    extract_cmd = run(source, "u07", tmp_path / "u07.csv", tmp_path / "privado", [ParserFake])
    status = {r.arquivo: (r.status, r.reconciliacao, r.motivo) for r in extract_cmd.reports}
    assert status == {
        "bom.fake": ("aceito", "ok", ""),
        "ruim.fake": ("rejeitado", "falhou", "ReconciliacaoFalhou"),
        "x.pdf": ("rejeitado", "nao_executada", "FormatoNaoReconhecido"),
    }
    assert extract_cmd.exit_code == 1
    assert len((tmp_path / "u07.csv").read_text("utf-8").splitlines()) == 2


def test_holder_name_from_one_file_removed_from_another(tmp_path):
    # the holder name comes from the parser; it appears as a company in a PIX with CNPJ -> review
    source = tmp_path / "raw"
    _write(source, "a.fake", "0.00;-1.00\n2024-01-02;PIX ENVIADO;-1.00;FULANO TAL LTDA;12.345.678/0001-90")
    extract_cmd = run(source, "u07", tmp_path / "u07.csv", tmp_path / "privado", [ParserFake])
    assert extract_cmd.reports[0].linhas_revisar == 1
    assert "FULANO" not in (tmp_path / "u07.csv").read_text("utf-8")


def test_run_all_joins_folders_and_uses_number_as_pseudonym(tmp_path):
    from statement.pipeline import run_all
    raw = tmp_path / "raw"
    _write(raw / "2", "a.fake", "0.00;-1.00\n2024-01-02;TARIFA;-1.00;;")
    _write(raw / "10", "b.fake", "0.00;5.00\n2024-01-03;PIX RECEBIDO;5.00;CICLANO EXEMPLO;")
    output = tmp_path / "saida" / "transacoes.csv"
    overall = run_all(raw, output.parent, output, tmp_path / "privado", [ParserFake])
    assert overall.exit_code == 0 and overall.lines == 2
    assert (output.parent / "u02.csv").exists() and (output.parent / "u10.csv").exists()
    assert output.read_text("utf-8").splitlines() == [
        "id_usuario,data,historico,contraparte,valor,tipo,meio,banco",
        "u02,2024-01-02,TARIFA,,-1.00,saida,tarifa,fakebank",
        "u10,2024-01-03,PIX RECEBIDO,PESSOA_FISICA,5.00,entrada,pix,fakebank",
    ]


class ParserFakeOtherHolder(ParserFake):
    name = "fake_outro_titular"

    @classmethod
    def detect(cls, path):
        return path.suffix == ".fake2"

    def extract(self, path):
        r = super().extract(path)
        r.holder_names = ["Beltrana Teste Souza"]
        return r


def test_run_all_holder_of_one_user_as_counterparty_of_another(tmp_path):
    from statement.pipeline import run_all
    raw = tmp_path / "raw"
    # u01 buys at the company that carries the name of u02's holder
    _write(raw / "1", "a.fake", "0.00;-9.00\n2024-01-02;COMPRA DEBITO;-9.00;BELTRANA TESTE DOCES;")
    _write(raw / "2", "b.fake2", "0.00;-1.00\n2024-01-02;TARIFA;-1.00;;")
    output = tmp_path / "saida" / "transacoes.csv"
    overall = run_all(raw, output.parent, output, tmp_path / "privado", [ParserFake, ParserFakeOtherHolder])
    assert overall.exit_code == 0
    assert overall.by_user["u01"].reports[0].linhas_revisar == 1
    assert "BELTRANA" not in output.read_text("utf-8")


def test_run_all_rejects_folder_without_number(tmp_path):
    from statement.pipeline import run_all
    (tmp_path / "raw" / "joao").mkdir(parents=True)
    with pytest.raises(ValueError):
        run_all(tmp_path / "raw", tmp_path, tmp_path / "t.csv", tmp_path, [ParserFake])


def test_invalid_user(tmp_path):
    with pytest.raises(ValueError):
        run(tmp_path, "07", tmp_path / "o.csv", tmp_path, [ParserFake])
