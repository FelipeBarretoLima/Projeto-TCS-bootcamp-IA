"""Repository against the real database (Supabase). Only runs with TESTE_BANCO=1.

    TESTE_BANCO=1 pytest database/tests/test_repository_real_db.py

Everything happens inside a transaction rolled back at the end: nothing is saved.
"""

import os
import uuid
from datetime import date
from decimal import Decimal

import psycopg
import pytest

from database.migrate import database_url
from database.repository import Database, DuplicateStatement

pytestmark = pytest.mark.skipif(os.environ.get("TESTE_BANCO") != "1", reason="defina TESTE_BANCO=1")


@pytest.fixture
def db():
    con = psycopg.connect(database_url(), prepare_threshold=None)
    try:
        yield Database(con)
    finally:
        con.rollback()
        con.close()


def _user(db):
    uid = uuid.uuid4()
    db.con.execute("insert into auth.users (id, email, aud, role) values (%s, %s, 'authenticated', 'authenticated')",
                   (uid, f"{uid}@teste.invalid"))
    return uid


def _t(day, amount="-8.94"):
    return {"data": date(2024, 1, day), "historico": "COMPRA", "contraparte": "UBER", "valor": Decimal(amount),
            "tipo": "saida", "meio": "cartao_credito", "banco": "nubank", "categoria": "transporte",
            "origem_categoria": "modelo"}


def test_full_flow(db):
    u = _user(db)
    g1 = db.save_statement(u, nome_arquivo="a.csv", hash_arquivo="h1", parser="p", periodo_inicio=date(2024, 1, 1),
                           periodo_fim=date(2024, 1, 31), transactions=[_t(2), _t(2)])
    assert (g1.saved, g1.duplicates) == (2, 0)
    g2 = db.save_statement(u, nome_arquivo="b.csv", hash_arquivo="h2", parser="p", periodo_inicio=None,
                           periodo_fim=None, transactions=[_t(2), _t(2), _t(2), _t(3)])
    assert (g2.saved, g2.duplicates) == (2, 2)
    with pytest.raises(DuplicateStatement):
        db.save_statement(u, nome_arquivo="a.csv", hash_arquivo="h1", parser="p", periodo_inicio=None,
                          periodo_fim=None, transactions=[_t(9)])
    assert len(db.transactions(u)) == 4 and len(db.list_statements(u)) == 2

    c = db.create_conversation(u, "teste")
    db.save_message(c, "usuario", "oi")
    db.save_message(c, "agente", "olá", {"tipo": "barras", "titulo": "t", "rotulos": [], "series": []})
    assert [m["papel"] for m in db.messages(c)] == ["usuario", "agente"]
    assert db.messages(c)[1]["grafico"]["titulo"] == "t"
    assert db.conversation_belongs_to_user(u, c) and not db.conversation_belongs_to_user(_user(db), c)

    # statement b also brought the two purchases of day 2: they move to it instead of disappearing
    assert db.delete_statement(u, g1.statement_id)
    assert len(db.transactions(u)) == 4
    [remaining] = db.list_statements(u)
    assert remaining["linhas_gravadas"] == 4
    assert db.delete_statement(u, g2.statement_id)
    assert db.transactions(u) == []


def test_find_transactions_with_filters(db):
    u, other = _user(db), _user(db)
    uncategorized = {**_t(20, "-1.00"), "categoria": None, "origem_categoria": None}
    grocery = {**_t(5, "-2.00"), "categoria": "mercado"}
    db.save_statement(u, nome_arquivo="a.csv", hash_arquivo="h1", parser="p", periodo_inicio=None,
                      periodo_fim=None, transactions=[_t(2), grocery, uncategorized])
    db.save_statement(other, nome_arquivo="b.csv", hash_arquivo="h1", parser="p", periodo_inicio=None,
                      periodo_fim=None, transactions=[_t(9)])

    assert [t["data"].day for t in db.find_transactions(u)] == [20, 5, 2]
    assert [t["data"].day for t in db.find_transactions(u, start=date(2024, 1, 3), end=date(2024, 1, 20))] == [20, 5]
    assert [t["data"].day for t in db.find_transactions(u, categoria="transporte")] == [2]
    assert [t["data"].day for t in db.find_transactions(u, uncategorized=True)] == [20]
    assert db.find_transactions(u, end=date(2024, 1, 4), categoria="mercado") == []
    assert "origem_categoria" not in db.find_transactions(u)[0]


def test_transaction_period(db):
    u = _user(db)
    assert db.transaction_period(u) == (None, None)
    db.save_statement(u, nome_arquivo="a.csv", hash_arquivo="h1", parser="p", periodo_inicio=None,
                      periodo_fim=None, transactions=[_t(9), _t(2, "-1.00"), _t(30, "-2.00")])
    assert db.transaction_period(u) == (date(2024, 1, 2), date(2024, 1, 30))


def test_corrections_and_retraining_history(db):
    u = _user(db)
    db.save_statement(u, nome_arquivo="a.csv", hash_arquivo="h1", parser="p", periodo_inicio=None,
                      periodo_fim=None, transactions=[_t(2), _t(3, "-1.00")])
    new_before = db.corrections_since_last_training()
    all_before = len(db.corrections_for_training())
    [a, b] = db._all("select id from public.transacoes where usuario_id = %s order by id", u)
    assert db.set_category(u, a["id"], "mercado")
    assert db.set_category(u, b["id"], None)  # "uncategorized" is not a training example
    assert db.corrections_since_last_training() == new_before + 1
    new = [c for c in db.corrections_for_training() if c["valor"] == Decimal("-8.94")][-1]
    assert len(db.corrections_for_training()) == all_before + 1
    assert new["categoria"] == "mercado" and new["corrigida_em"] is not None
    assert "original_cifrado" not in new

    tid = db.start_training()
    assert db.training_running()
    db.finish_training(tid, status="ok", correcoes=1, linhas_treino=10, acerto_correcoes_antes=0,
                       acerto_correcoes_depois=100, acerto_base_depois=98.5)
    assert not db.training_running() and db.trainings(1)[0]["status"] == "ok"
    # the "ok" training started after the correction: the counter resets
    assert db.corrections_since_last_training() == 0


_TRY_USER_LOCK = "select pg_try_advisory_xact_lock(hashtextextended(%s::text, 0))"


def test_import_locks_only_the_same_user_until_commit(db):
    u = _user(db)
    db.save_statement(u, nome_arquivo="a.csv", hash_arquivo="h-trava", parser="p", periodo_inicio=None,
                      periodo_fim=None, transactions=[_t(5)])
    # another connection (another request) while the first import has not finished
    other = psycopg.connect(database_url(), prepare_threshold=None)
    try:
        assert other.execute(_TRY_USER_LOCK, (str(u),)).fetchone()[0] is False
        assert other.execute(_TRY_USER_LOCK, (str(uuid.uuid4()),)).fetchone()[0] is True
    finally:
        other.rollback()
        other.close()


def test_one_retraining_at_a_time_even_on_another_connection(db):
    assert db.start_training_if_free() is not None
    other = psycopg.connect(database_url(), prepare_threshold=None)
    try:
        other.execute("set lock_timeout = '500ms'")
        with pytest.raises(psycopg.errors.LockNotAvailable):
            Database(other).start_training_if_free()  # waits for the lock instead of starting another
    finally:
        other.rollback()
        other.close()


def _corrections(db, u):
    return db._all("select transacao_id, categoria from public.correcoes where usuario_id = %s order by id", u)


def test_correction_survives_statement_deletion(db):
    """Requires migration 0005 applied (python -m database.migrate)."""
    u = _user(db)
    g = db.save_statement(u, nome_arquivo="a.csv", hash_arquivo="h-corr-1", parser="p", periodo_inicio=None,
                          periodo_fim=None, transactions=[_t(5)])
    [t] = db.find_transactions(u)
    assert db.set_category(u, t["id"], "mercado")
    assert db.set_category(u, t["id"], "compras")  # correcting again updates the same row
    assert _corrections(db, u) == [{"transacao_id": t["id"], "categoria": "compras"}]
    assert db.delete_statement(u, g.statement_id)
    assert _corrections(db, u) == [{"transacao_id": None, "categoria": "compras"}]
    # the same statement imported again and corrected: the old correction gives way to the new one
    db.save_statement(u, nome_arquivo="a.csv", hash_arquivo="h-corr-2", parser="p", periodo_inicio=None,
                      periodo_fim=None, transactions=[_t(5)])
    [t2] = db.find_transactions(u)
    assert db.set_category(u, t2["id"], "mercado")
    assert _corrections(db, u) == [{"transacao_id": t2["id"], "categoria": "mercado"}]
    assert db.set_category(u, t2["id"], None)  # uncategorized undoes the correction
    assert _corrections(db, u) == []
