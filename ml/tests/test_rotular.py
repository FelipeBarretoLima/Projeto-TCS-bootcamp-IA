"""Rotulagem do treino (módulo ml). Dados inventados."""

import csv

import pytest

from extrato.modelos import COLUNAS, PESSOA_FISICA, Meio, Tipo
from ml import rotular as rot
from ml.classes import Categoria, por_regra

S, E = Tipo.SAIDA, Tipo.ENTRADA


@pytest.mark.parametrize("meio,tipo,historico,contraparte,esperado", [
    (Meio.TARIFA, S, "TARIFA", "", Categoria.FINANCEIRO),
    (Meio.INVESTIMENTO, E, "RESGATE", "", Categoria.FINANCEIRO),
    (Meio.PAGAMENTO_FATURA, S, "PAGAMENTO DE FATURA", "", Categoria.FINANCEIRO),
    (Meio.SALARIO, E, "CREDITO DE SALARIO", "", Categoria.RECEITAS),
    (Meio.PIX, E, "PIX RECEBIDO", PESSOA_FISICA, Categoria.RECEITAS),
    (Meio.CARTAO_CREDITO, E, "VALOR ADICIONADO", "", Categoria.FINANCEIRO),
    (Meio.BOLETO, S, "PAGAMENTO DE BOLETO", PESSOA_FISICA, Categoria.CONTAS_SERVICOS),
    (Meio.PIX, S, "PIX ENVIADO", PESSOA_FISICA, Categoria.TRANSFERENCIA_PESSOA),
    (Meio.CARTAO_DEBITO, S, "COMPRA", PESSOA_FISICA, Categoria.TRANSFERENCIA_PESSOA),
    (Meio.OUTROS, S, "RECARGA DE CELULAR", "", Categoria.CONTAS_SERVICOS),
    (Meio.CARTAO_DEBITO, S, "COMPRA", "PADARIA MODELO", None),  # depende do nome
    (Meio.PIX, S, "PIX ENVIADO", "EMPRESA FICTICIA LTDA", None),
])
def test_regras(meio, tipo, historico, contraparte, esperado):
    assert por_regra(meio, tipo, historico, contraparte) == esperado


def _mapa(pasta, nome, linhas):
    with open(pasta / nome, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rot.COLUNAS_MAPA, lineterminator="\n")
        w.writeheader()
        for l in linhas:
            w.writerow({c: l.get(c, "") for c in rot.COLUNAS_MAPA})


def test_mapa_casa_pelo_nome_base_e_branco_aceita_sugestao(tmp_path):
    _mapa(tmp_path, rot.ARQ_REVISADO, [
        {"contraparte": "PADARIA MODELO 12", "classe_sugerida": "mercado", "linhas": "5"},
        {"contraparte": "LOJA X", "classe_sugerida": "compras", "classe": "alimentacao_fora"},
    ])
    _mapa(tmp_path, rot.ARQ_NOVOS, [{"contraparte": "POSTO FICTICIO", "classe_sugerida": "transporte"},
                                    {"contraparte": "LOJA X", "classe_sugerida": "mercado"}])  # revisado vence
    assert rot.carrega_mapa(tmp_path) == {
        "PADARIA MODELO": Categoria.MERCADO, "LOJA X": Categoria.ALIMENTACAO_FORA, "POSTO FICTICIO": Categoria.TRANSPORTE}


def test_classe_invalida_no_mapa_e_erro(tmp_path):
    _mapa(tmp_path, rot.ARQ_REVISADO, [{"contraparte": "LOJA X", "classe": "comida"}])
    with pytest.raises(ValueError):
        rot.carrega_mapa(tmp_path)


def _csv_parser(caminho, linhas):
    with open(caminho, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(COLUNAS)
        w.writerows(linhas)


def test_rotulado_e_o_csv_do_parser_mais_categoria(tmp_path):
    entrada, saida, privado = tmp_path / "t.csv", tmp_path / "ml" / "r.csv", tmp_path / "privado"
    privado.mkdir()
    _mapa(privado, rot.ARQ_REVISADO, [{"contraparte": "PADARIA MODELO", "classe_sugerida": "mercado"}])
    linhas = [
        ["u01", "2024-01-02", "COMPRA NO DÉBITO", "PADARIA MODELO", "-10.00", "saida", "cartao_debito", "nubank"],
        ["u01", "2024-01-03", "TARIFA", "", "-5.00", "saida", "tarifa", "nubank"],
        ["u01", "2024-01-04", "COMPRA NO DÉBITO", "LOJA NUNCA VISTA", "-7.00", "saida", "cartao_debito", "nubank"],
        # PIX para empresa chega sem a padronização do cartão: casa pelo nome-base mesmo assim
        ["u01", "2024-01-05", "PIX ENVIADO", "PADARIA MODELO 12", "-3.00", "saida", "pix", "nubank"],
    ]
    _csv_parser(entrada, linhas)
    res = rot.rotula(entrada, saida, privado)
    saida_linhas = list(csv.reader(open(saida, encoding="utf-8")))
    assert saida_linhas[0] == [*COLUNAS, "categoria"]
    assert [l[:-1] for l in saida_linhas[1:]] == linhas  # colunas do parser intactas
    assert [l[-1] for l in saida_linhas[1:]] == ["mercado", "financeiro", "", "mercado"]
    assert res.novos_no_mapa == 1  # a loja nova entra na lista para classificar
    assert rot.rotula(entrada, saida, privado).novos_no_mapa == 0  # e não entra de novo


def test_entrada_fora_do_contrato_e_erro(tmp_path):
    (tmp_path / "t.csv").write_text("a,b\n1,2\n", "utf-8")
    with pytest.raises(ValueError):
        rot.rotula(tmp_path / "t.csv", tmp_path / "r.csv", tmp_path)


def test_novos_so_acrescenta_e_nao_apaga_o_que_foi_preenchido(tmp_path):
    _mapa(tmp_path, rot.ARQ_REVISADO, [{"contraparte": "LOJA JA MAPEADA", "classe_sugerida": "compras"}])
    assert rot.atualiza_novos(tmp_path, ["POSTO FICTICIO", "POSTO FICTICIO", "LOJA JA MAPEADA", PESSOA_FISICA]) == 1
    linhas = list(csv.DictReader(open(tmp_path / rot.ARQ_NOVOS, encoding="utf-8")))
    assert [(l["contraparte"], l["linhas"], l["classe_sugerida"]) for l in linhas] == [("POSTO FICTICIO", "2", "transporte")]
    linhas[0]["classe"] = "transporte"
    _mapa(tmp_path, rot.ARQ_NOVOS, linhas)
    assert rot.atualiza_novos(tmp_path, ["POSTO FICTICIO", "BAR FICTICIO"]) == 1
    depois = list(csv.DictReader(open(tmp_path / rot.ARQ_NOVOS, encoding="utf-8")))
    assert [(l["contraparte"], l["classe"]) for l in depois] == [("POSTO FICTICIO", "transporte"), ("BAR FICTICIO", "")]
