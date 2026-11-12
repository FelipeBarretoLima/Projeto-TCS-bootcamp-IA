"""Repositório contra o banco de verdade (Supabase). Só roda com TESTE_BANCO=1.

    TESTE_BANCO=1 pytest database/tests/test_repositorio_banco_real.py

Tudo acontece numa transação desfeita no fim: nada fica gravado.
"""

import os
import uuid
from datetime import date
from decimal import Decimal

import psycopg
import pytest

from database.migrate import url_do_banco
from database.repository import Banco, ExtratoRepetido

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

    # o extrato b também trazia as duas compras do dia 2: elas passam para ele em vez de sumir
    assert db.apaga_extrato(u, g1.extrato_id)
    assert len(db.transacoes(u)) == 4
    [restante] = db.lista_extratos(u)
    assert restante["linhas_gravadas"] == 4
    assert db.apaga_extrato(u, g2.extrato_id)
    assert db.transacoes(u) == []


def test_busca_transacoes_com_filtros(db):
    u, outro = _usuario(db), _usuario(db)
    sem = {**_t(20, "-1.00"), "categoria": None, "origem_categoria": None}
    mercado = {**_t(5, "-2.00"), "categoria": "mercado"}
    db.grava_extrato(u, nome_arquivo="a.csv", hash_arquivo="h1", parser="p", periodo_inicio=None,
                     periodo_fim=None, transacoes=[_t(2), mercado, sem])
    db.grava_extrato(outro, nome_arquivo="b.csv", hash_arquivo="h1", parser="p", periodo_inicio=None,
                     periodo_fim=None, transacoes=[_t(9)])

    assert [t["data"].day for t in db.busca_transacoes(u)] == [20, 5, 2]
    assert [t["data"].day for t in db.busca_transacoes(u, inicio=date(2024, 1, 3), fim=date(2024, 1, 20))] == [20, 5]
    assert [t["data"].day for t in db.busca_transacoes(u, categoria="transporte")] == [2]
    assert [t["data"].day for t in db.busca_transacoes(u, sem_categoria=True)] == [20]
    assert db.busca_transacoes(u, fim=date(2024, 1, 4), categoria="mercado") == []
    assert "origem_categoria" not in db.busca_transacoes(u)[0]


def test_periodo_transacoes(db):
    u = _usuario(db)
    assert db.periodo_transacoes(u) == (None, None)
    db.grava_extrato(u, nome_arquivo="a.csv", hash_arquivo="h1", parser="p", periodo_inicio=None,
                     periodo_fim=None, transacoes=[_t(9), _t(2, "-1.00"), _t(30, "-2.00")])
    assert db.periodo_transacoes(u) == (date(2024, 1, 2), date(2024, 1, 30))


def test_correcoes_e_historico_de_retreino(db):
    u = _usuario(db)
    db.grava_extrato(u, nome_arquivo="a.csv", hash_arquivo="h1", parser="p", periodo_inicio=None,
                     periodo_fim=None, transacoes=[_t(2), _t(3, "-1.00")])
    novas_antes = db.correcoes_desde_ultimo_treino()
    todas_antes = len(db.correcoes_para_treino())
    [a, b] = db._todas("select id from public.transacoes where usuario_id = %s order by id", u)
    assert db.muda_categoria(u, a["id"], "mercado")
    assert db.muda_categoria(u, b["id"], None)  # "sem categoria" não é exemplo de treino
    assert db.correcoes_desde_ultimo_treino() == novas_antes + 1
    nova = [c for c in db.correcoes_para_treino() if c["valor"] == Decimal("-8.94")][-1]
    assert len(db.correcoes_para_treino()) == todas_antes + 1
    assert nova["categoria"] == "mercado" and nova["corrigida_em"] is not None
    assert "original_cifrado" not in nova

    tid = db.inicia_treino()
    assert db.treino_rodando()
    db.conclui_treino(tid, status="ok", correcoes=1, linhas_treino=10, acerto_correcoes_antes=0,
                      acerto_correcoes_depois=100, acerto_base_depois=98.5)
    assert not db.treino_rodando() and db.treinos(1)[0]["status"] == "ok"
    # o treino "ok" começou depois da correção: o contador zera
    assert db.correcoes_desde_ultimo_treino() == 0
