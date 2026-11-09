"""Repositório contra o banco de verdade (Supabase). Só roda com TESTE_BANCO=1.

    TESTE_BANCO=1 pytest banco/tests/test_repositorio_banco_real.py

Tudo acontece numa transação desfeita no fim: nada fica gravado.
"""

import os
import uuid
from datetime import date
from decimal import Decimal

import psycopg
import pytest

from banco.migrar import url_do_banco
from banco.repositorio import Banco, ExtratoRepetido

pytestmark = pytest.mark.skipif(os.environ.get("TESTE_BANCO") != "1", reason="defina TESTE_BANCO=1")


@pytest.fixture
def db():
    con = psycopg.connect(url_do_banco(), prepare_threshold=None)
    try:
        yield Banco(con)
    finally:
        con.rollback()
        con.close()


def _usuario(db):
    uid = uuid.uuid4()
    db.con.execute("insert into auth.users (id, email, aud, role) values (%s, %s, 'authenticated', 'authenticated')",
                   (uid, f"{uid}@teste.invalid"))
    return uid


def _t(dia, valor="-8.94"):
    return {"data": date(2024, 1, dia), "historico": "COMPRA", "contraparte": "UBER", "valor": Decimal(valor),
            "tipo": "saida", "meio": "cartao_credito", "banco": "nubank", "categoria": "transporte",
            "origem_categoria": "modelo"}


def test_fluxo_completo(db):
    u = _usuario(db)
    g1 = db.grava_extrato(u, nome_arquivo="a.csv", hash_arquivo="h1", parser="p", periodo_inicio=date(2024, 1, 1),
                          periodo_fim=date(2024, 1, 31), transacoes=[_t(2), _t(2)])
    assert (g1.gravadas, g1.repetidas) == (2, 0)
    g2 = db.grava_extrato(u, nome_arquivo="b.csv", hash_arquivo="h2", parser="p", periodo_inicio=None,
                          periodo_fim=None, transacoes=[_t(2), _t(2), _t(2), _t(3)])
    assert (g2.gravadas, g2.repetidas) == (2, 2)
    with pytest.raises(ExtratoRepetido):
        db.grava_extrato(u, nome_arquivo="a.csv", hash_arquivo="h1", parser="p", periodo_inicio=None,
                         periodo_fim=None, transacoes=[_t(9)])
    assert len(db.transacoes(u)) == 4 and len(db.lista_extratos(u)) == 2

    c = db.cria_conversa(u, "teste")
    db.grava_mensagem(c, "usuario", "oi")
    db.grava_mensagem(c, "agente", "olá", {"tipo": "barras", "titulo": "t", "rotulos": [], "series": []})
    assert [m["papel"] for m in db.mensagens(c)] == ["usuario", "agente"]
    assert db.mensagens(c)[1]["grafico"]["titulo"] == "t"
    assert db.conversa_e_do_usuario(u, c) and not db.conversa_e_do_usuario(_usuario(db), c)

    assert db.apaga_extrato(u, g1.extrato_id)
    assert len(db.transacoes(u)) == 2
