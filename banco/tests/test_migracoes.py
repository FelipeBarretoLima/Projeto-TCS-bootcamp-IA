"""Migrações: conferidas sem banco (o SQL tem que bater com as classes do Python)."""

import re

from api.esquemas import Transacao
from banco.migrar import migracoes
from extrato.modelos import Meio, Tipo
from ml.classes import Categoria

SQL = "\n".join(m.read_text("utf-8") for m in migracoes())


def _valores_do_check(coluna: str) -> set[str]:
    m = re.search(rf"\b{coluna}\b[^\n]*?check \({coluna} in \((.*?)\)\)", SQL, re.S)
    assert m, f"check de {coluna} não encontrado"
    return set(re.findall(r"'([^']+)'", m.group(1)))


def test_migracoes_numeradas_em_ordem():
    nomes = [m.name for m in migracoes()]
    assert nomes and all(re.fullmatch(r"\d{4}_[a-z0-9_]+\.sql", n) for n in nomes)
    assert [int(n[:4]) for n in nomes] == list(range(1, len(nomes) + 1))


def test_categorias_iguais_as_do_modelo():
    assert _valores_do_check("categoria") == {c.value for c in Categoria}


def test_meios_e_tipos_iguais_aos_do_parser():
    assert _valores_do_check("meio") == {m.value for m in Meio}
    assert _valores_do_check("tipo") == {t.value for t in Tipo}


def test_origens_cobrem_as_da_api_mais_correcao_do_usuario():
    da_api = set(Transacao.model_fields["origem_categoria"].annotation.__args__[0].__args__)
    assert _valores_do_check("origem_categoria") == da_api | {"usuario"}


def test_nenhuma_coluna_de_senha():
    # a senha fica no Supabase Auth; aqui olhamos só o código, sem os comentários "--"
    codigo = re.sub(r"--[^\n]*", "", SQL)
    assert not re.search(r"senha|password", codigo, re.I)
