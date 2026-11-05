"""Registro, reconciliação e pipeline ponta a ponta com um parser de mentira."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from extrato.modelos import Meio
from extrato.normalizacao import normaliza_historico, valor_br
from extrato.parsers.base import (
    FormatoAmbiguo, FormatoNaoReconhecido, Parser, ResultadoExtracao, Segmento, TransacaoBruta,
)
from extrato.parsers.registro import escolhe_parser
from extrato.pipeline import executa
from extrato.reconciliacao import ReconciliacaoFalhou, reconcilia

D = Decimal


class ParserFake(Parser):
    """Lê um .fake inventado: 'saldo_inicial;saldo_final' e depois 'AAAA-MM-DD;historico;valor;nome;doc'."""

    nome, banco, produto = "fake_conta", "fakebank", "conta"
    MEIOS = {"PIX ENVIADO": Meio.PIX, "PIX RECEBIDO": Meio.PIX, "COMPRA DEBITO": Meio.CARTAO_DEBITO,
             "TARIFA": Meio.TARIFA}

    @classmethod
    def detecta(cls, caminho):
        return caminho.suffix == ".fake"

    def extrai(self, caminho):
        linhas = caminho.read_text("utf-8").splitlines()
        ini, fim = (D(x) for x in linhas[0].split(";"))
        txs = []
        for l in linhas[1:]:
            d, h, v, n, doc = l.split(";")
            txs.append(TransacaoBruta(date.fromisoformat(d), h, D(v), 0, n, doc))
        return ResultadoExtracao(self.banco, self.produto, txs, [Segmento("arquivo", ini, fim)],
                                 nomes_titulares=["Fulano de Tal Exemplo"])


class OutroFake(ParserFake):
    nome = "outro_fake"


# --- registro ---

def test_nenhum_parser_reconhece(tmp_path):
    with pytest.raises(FormatoNaoReconhecido):
        escolhe_parser(tmp_path / "x.pdf", [ParserFake])


def test_mais_de_um_parser_reconhece(tmp_path):
    with pytest.raises(FormatoAmbiguo):
        escolhe_parser(tmp_path / "x.fake", [ParserFake, OutroFake])


def test_exatamente_um_parser(tmp_path):
    assert isinstance(escolhe_parser(tmp_path / "x.fake", [ParserFake]), ParserFake)


# --- reconciliação ---

def _res(valores, abertura, fechamento):
    txs = [TransacaoBruta(date(2024, 1, 1), "TARIFA", D(v), 0) for v in valores]
    return ResultadoExtracao("x", "conta", txs, [Segmento("s", D(abertura), D(fechamento))])


def test_reconciliacao_ok():
    assert reconcilia(_res(["-10.00", "5.50"], "100.00", "95.50")).ok


def test_reconciliacao_falha_por_um_centavo():
    with pytest.raises(ReconciliacaoFalhou):
        reconcilia(_res(["-10.00", "5.50"], "100.00", "95.49"))


def test_reconciliacao_sem_totais_rejeita():
    with pytest.raises(ReconciliacaoFalhou):
        reconcilia(ResultadoExtracao("x", "conta", [], []))


def test_rejeicao_por_documento_tira_so_o_documento_que_nao_fecha():
    from extrato.reconciliacao import separa_documentos_divergentes
    txs = [TransacaoBruta(date(2024, 1, 1), "TARIFA", D("-1.00"), (0,)),
           TransacaoBruta(date(2024, 2, 1), "TARIFA", D("-2.00"), (1,)),
           TransacaoBruta(date(2024, 2, 2), "TARIFA", D("-3.00"), (1, 2))]
    segs = [Segmento("a", D(0), D("-1.00"), "fatura A"),
            Segmento("b", D(0), D("-9.00"), "fatura B"),  # não fecha
            Segmento("b2", D(0), D("-3.00"), "fatura B")]
    r, ruins = separa_documentos_divergentes(ResultadoExtracao("x", "cartao", txs, segs))
    assert ruins == ["fatura B"]
    assert [t.valor for t in r.transacoes] == [D("-1.00")]
    assert reconcilia(r).ok


def test_rejeicao_por_documento_exige_rotulo_de_documento():
    from extrato.reconciliacao import separa_documentos_divergentes
    with pytest.raises(ReconciliacaoFalhou):
        separa_documentos_divergentes(_res(["-1.00"], "0.00", "-1.00"))


def test_transacao_em_segmento_inexistente_rejeita():
    r = _res(["-1.00"], "1.00", "0.00")
    r.transacoes.append(TransacaoBruta(date(2024, 1, 1), "TARIFA", D("0.00"), 5))
    with pytest.raises(ReconciliacaoFalhou):
        reconcilia(r)


# --- normalização ---

def test_normaliza_historico():
    assert normaliza_historico("  Pix   enviado - 123456 ") == "PIX ENVIADO"


@pytest.mark.parametrize("txt,esperado", [
    ("1.234,56", "1234.56"), ("R$ 1.234,56", "1234.56"), ("-R$ 1,00", "-1.00"),
    ("R$ -1,00", "-1.00"), ("999,99-", "-999.99"), ("+0,10", "0.10"),
])
def test_valor_br(txt, esperado):
    assert valor_br(txt) == D(esperado)


@pytest.mark.parametrize("txt", ["1,2", "abc", "-1,00-", "1.23,45"])
def test_valor_br_invalido(txt):
    with pytest.raises(ValueError):
        valor_br(txt)


# --- ponta a ponta ---

def _escreve(pasta: Path, nome: str, conteudo: str) -> None:
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / nome).write_text(conteudo, "utf-8")


def test_pipeline_ponta_a_ponta(tmp_path):
    entrada = tmp_path / "raw"
    _escreve(entrada, "a.fake", "\n".join([
        "100.00;64.50",
        "2024-01-02;Pix enviado;-20.00;CICLANO EXEMPLO;•••.456.789-••",
        "2024-01-03;COMPRA DEBITO;-10.50;PADARIA MODELO 12.345.678/0001-90;",
        "2024-01-04;PIX RECEBIDO;5.00;JOAO EXEMPLO ME;",  # ambíguo -> revisar
        "2024-01-05;TARIFA;-10.00;;",
    ]))
    saida, privado = tmp_path / "saida" / "u07.csv", tmp_path / "privado"
    ex = executa(entrada, "u07", saida, privado, [ParserFake])

    assert ex.codigo_saida == 0
    assert saida.read_text("utf-8").splitlines() == [
        "id_usuario,data,historico,contraparte,valor,tipo,meio,banco",
        "u07,2024-01-02,PIX ENVIADO,PESSOA_FISICA,-20.00,saida,pix,fakebank",
        "u07,2024-01-03,COMPRA DEBITO,PADARIA MODELO,-10.50,saida,cartao_debito,fakebank",
        "u07,2024-01-05,TARIFA,,-10.00,saida,tarifa,fakebank",
    ]
    rel = ex.relatorios[0]
    assert (rel.status, rel.reconciliacao, rel.linhas_extraidas, rel.linhas_gravadas, rel.linhas_revisar) == (
        "aceito", "ok", 4, 3, 1)
    assert (privado / "revisar.csv").exists()
    assert (saida.parent / "u07.relatorio.csv").exists()


def test_historico_desconhecido_rejeita_o_arquivo(tmp_path):
    entrada = tmp_path / "raw"
    _escreve(entrada, "a.fake", "0.00;-1.00\n2024-01-02;LANCAMENTO NOVO;-1.00;;")
    ex = executa(entrada, "u07", tmp_path / "u07.csv", tmp_path / "privado", [ParserFake])
    assert ex.codigo_saida == 1
    assert ex.relatorios[0].motivo == "HistoricoDesconhecido"
    assert not (tmp_path / "u07.csv").exists()
    assert "LANCAMENTO NOVO" in (tmp_path / "privado" / "historicos_desconhecidos.csv").read_text("utf-8")


def test_reconciliacao_divergente_rejeita_e_aceita_o_resto(tmp_path):
    entrada = tmp_path / "raw"
    _escreve(entrada, "ruim.fake", "0.00;-2.00\n2024-01-02;TARIFA;-1.00;;")
    _escreve(entrada, "bom.fake", "0.00;-1.00\n2024-01-02;TARIFA;-1.00;;")
    _escreve(entrada, "x.pdf", "nao e pdf")
    ex = executa(entrada, "u07", tmp_path / "u07.csv", tmp_path / "privado", [ParserFake])
    status = {r.arquivo: (r.status, r.reconciliacao, r.motivo) for r in ex.relatorios}
    assert status == {
        "bom.fake": ("aceito", "ok", ""),
        "ruim.fake": ("rejeitado", "falhou", "ReconciliacaoFalhou"),
        "x.pdf": ("rejeitado", "nao_executada", "FormatoNaoReconhecido"),
    }
    assert ex.codigo_saida == 1
    assert len((tmp_path / "u07.csv").read_text("utf-8").splitlines()) == 2


def test_nome_do_titular_de_um_arquivo_e_removido_de_outro(tmp_path):
    # o nome do titular vem do parser; aparece como empresa num PIX com CNPJ -> revisar
    entrada = tmp_path / "raw"
    _escreve(entrada, "a.fake", "0.00;-1.00\n2024-01-02;PIX ENVIADO;-1.00;FULANO TAL LTDA;12.345.678/0001-90")
    ex = executa(entrada, "u07", tmp_path / "u07.csv", tmp_path / "privado", [ParserFake])
    assert ex.relatorios[0].linhas_revisar == 1
    assert "FULANO" not in (tmp_path / "u07.csv").read_text("utf-8")


def test_executa_tudo_junta_pastas_e_usa_numero_como_pseudonimo(tmp_path):
    from extrato.pipeline import executa_tudo
    raw = tmp_path / "raw"
    _escreve(raw / "2", "a.fake", "0.00;-1.00\n2024-01-02;TARIFA;-1.00;;")
    _escreve(raw / "10", "b.fake", "0.00;5.00\n2024-01-03;PIX RECEBIDO;5.00;CICLANO EXEMPLO;")
    saida = tmp_path / "saida" / "transacoes.csv"
    geral = executa_tudo(raw, saida.parent, saida, tmp_path / "privado", [ParserFake])
    assert geral.codigo_saida == 0 and geral.linhas == 2
    assert (saida.parent / "u02.csv").exists() and (saida.parent / "u10.csv").exists()
    assert saida.read_text("utf-8").splitlines() == [
        "id_usuario,data,historico,contraparte,valor,tipo,meio,banco",
        "u02,2024-01-02,TARIFA,,-1.00,saida,tarifa,fakebank",
        "u10,2024-01-03,PIX RECEBIDO,PESSOA_FISICA,5.00,entrada,pix,fakebank",
    ]


class ParserFakeOutroTitular(ParserFake):
    nome = "fake_outro_titular"

    @classmethod
    def detecta(cls, caminho):
        return caminho.suffix == ".fake2"

    def extrai(self, caminho):
        r = super().extrai(caminho)
        r.nomes_titulares = ["Beltrana Teste Souza"]
        return r


def test_executa_tudo_titular_de_um_usuario_como_contraparte_de_outro(tmp_path):
    from extrato.pipeline import executa_tudo
    raw = tmp_path / "raw"
    # u01 compra na empresa que leva o nome da titular do u02
    _escreve(raw / "1", "a.fake", "0.00;-9.00\n2024-01-02;COMPRA DEBITO;-9.00;BELTRANA TESTE DOCES;")
    _escreve(raw / "2", "b.fake2", "0.00;-1.00\n2024-01-02;TARIFA;-1.00;;")
    saida = tmp_path / "saida" / "transacoes.csv"
    geral = executa_tudo(raw, saida.parent, saida, tmp_path / "privado", [ParserFake, ParserFakeOutroTitular])
    assert geral.codigo_saida == 0
    assert geral.por_usuario["u01"].relatorios[0].linhas_revisar == 1
    assert "BELTRANA" not in saida.read_text("utf-8")


def test_executa_tudo_recusa_pasta_sem_numero(tmp_path):
    from extrato.pipeline import executa_tudo
    (tmp_path / "raw" / "joao").mkdir(parents=True)
    with pytest.raises(ValueError):
        executa_tudo(tmp_path / "raw", tmp_path, tmp_path / "t.csv", tmp_path, [ParserFake])


def test_usuario_invalido(tmp_path):
    with pytest.raises(ValueError):
        executa(tmp_path, "07", tmp_path / "o.csv", tmp_path, [ParserFake])
