"""Dashboard and chat. Gemini is replaced by a fixed answer (no external call)."""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from agent.assistant import Answer
from api.dependencies import assistant_model
from api.main import app
from api.routes import assistant as route

from api.tests.fakes import OTHER_USER, USER

CHART = {"tipo": "barras", "titulo": "Teste", "rotulos": ["jan/24"],
         "series": [{"nome": "Gastos", "valores": [10.0]}], "formato": "moeda"}


@pytest.fixture
def calls(monkeypatch):
    made = []

    def fake_answer(model, df, question, history=()):
        made.append({"question": question, "history": list(history), "rows": len(df)})
        return Answer(f"resposta para: {question}", CHART)

    app.dependency_overrides[assistant_model] = lambda: object()
    monkeypatch.setattr(route, "answer", fake_answer)
    return made


def _transaction(db, day, amount, kind, category, user=USER):
    db.rows.append({"usuario_id": user.id, "extrato_id": None, "data": day, "historico": "X",
                    "contraparte": "LOJA", "valor": Decimal(amount), "tipo": kind, "meio": "pix",
                    "banco": "nubank", "categoria": category, "origem_categoria": "regra"})


def test_dashboard_without_data():
    r = TestClient(app).get("/api/painel").json()
    assert r["tem_dados"] is False and r["grafico"] is None


def test_dashboard_with_data(db):
    _transaction(db, date(2024, 1, 5), "1000.00", "entrada", "receitas")
    _transaction(db, date(2024, 2, 5), "3000.00", "entrada", "receitas")
    _transaction(db, date(2024, 2, 6), "-200.00", "saida", "mercado")
    _transaction(db, date(2024, 2, 7), "-500.00", "saida", "financeiro")   # paying the card bill is not an expense
    _transaction(db, date(2024, 2, 8), "-999.00", "saida", "mercado", OTHER_USER)  # from another user
    r = TestClient(app).get("/api/painel").json()
    assert (r["mes"], r["receitas"], r["despesas"], r["saldo"]) == ("fev/24", 3000.0, 200.0, 2800.0)
    assert r["grafico"]["rotulos"][-2:] == ["jan/24", "fev/24"]


def test_chat_creates_a_conversation_and_keeps_the_messages(db, calls):
    _transaction(db, date(2024, 1, 5), "-10.00", "saida", "mercado")
    client = TestClient(app)
    r = client.post("/api/chat", json={"mensagem": "quanto gastei de mercado?"}).json()
    assert r["resposta"]["texto"] == "resposta para: quanto gastei de mercado?"
    assert r["resposta"]["grafico"]["titulo"] == "Teste"
    assert calls[0]["rows"] == 1 and calls[0]["history"] == []
    [conversation] = client.get("/api/conversas").json()
    assert conversation["id"] == r["conversa_id"] and conversation["titulo"] == "quanto gastei de mercado?"

    # continuing the conversation sends the history
    client.post("/api/chat", json={"mensagem": "e transporte?", "conversa_id": r["conversa_id"]})
    assert [m["texto"] for m in calls[1]["history"]] == [
        "quanto gastei de mercado?", "resposta para: quanto gastei de mercado?"]
    messages = client.get(f"/api/conversas/{r['conversa_id']}/mensagens").json()
    assert [m["papel"] for m in messages] == ["usuario", "agente", "usuario", "agente"]


def test_long_title_is_cut(calls):
    r = TestClient(app).post("/api/chat", json={"mensagem": "a" * 200}).json()
    [c] = TestClient(app).get("/api/conversas").json()
    assert len(c["titulo"]) == 60 and c["titulo"].endswith("…") and r["conversa_id"] == c["id"]


def test_another_users_conversation_gives_404(calls, logged_in_as):
    cid = TestClient(app).post("/api/chat", json={"mensagem": "oi"}).json()["conversa_id"]
    logged_in_as(OTHER_USER)
    client = TestClient(app)
    assert client.get(f"/api/conversas/{cid}/mensagens").status_code == 404
    assert client.post("/api/chat", json={"mensagem": "oi", "conversa_id": cid}).status_code == 404
    assert client.delete(f"/api/conversas/{cid}").status_code == 404
    assert client.get("/api/conversas").json() == []


def test_assistant_error_saves_nothing(db, monkeypatch):
    def breaks(*_a, **_k):
        raise RuntimeError("Gemini fora do ar")

    app.dependency_overrides[assistant_model] = lambda: object()
    monkeypatch.setattr(route, "answer", breaks)
    r = TestClient(app).post("/api/chat", json={"mensagem": "oi"})
    assert r.status_code == 502
    assert db.messages_ == []


def test_empty_message_gives_422_or_400(calls):
    client = TestClient(app)
    assert client.post("/api/chat", json={"mensagem": ""}).status_code == 422
    assert client.post("/api/chat", json={"mensagem": "   "}).status_code == 400


def test_conversation_deleted_during_the_answer_gives_404_without_saving(db, calls, monkeypatch):
    client = TestClient(app)
    cid = client.post("/api/chat", json={"mensagem": "oi"}).json()["conversa_id"]

    def deletes_midway(model, df, question, history=()):
        db.delete_conversation(USER.id, __import__("uuid").UUID(cid))  # another tab deleted it
        return Answer("tarde demais", None)

    monkeypatch.setattr(route, "answer", deletes_midway)
    r = client.post("/api/chat", json={"mensagem": "e agora?", "conversa_id": cid})
    assert r.status_code == 404 and "apagada" in r.json()["detail"]


def test_no_connection_stays_open_while_the_llm_answers(db, monkeypatch):
    """With the connection held during the LLM (2 to 30 s), 5 slow questions exhausted the pool."""
    from contextlib import contextmanager

    from api.dependencies import database, open_database

    open_connections = []

    @contextmanager
    def counts_connections():
        open_connections.append(1)
        try:
            yield db
        finally:
            open_connections.pop()

    def whole_request_connection():  # the old dependency, which held the connection until the end
        with counts_connections() as d:
            yield d

    app.dependency_overrides[database] = whole_request_connection

    def answer_checking(model, df, question, history=()):
        assert open_connections == [], "havia uma conexão do banco aberta durante a chamada ao LLM"
        return Answer("ok", None)

    app.dependency_overrides[open_database] = lambda: counts_connections
    app.dependency_overrides[assistant_model] = lambda: object()
    monkeypatch.setattr(route, "answer", answer_checking)
    client = TestClient(app)
    cid = client.post("/api/chat", json={"mensagem": "oi"}).json()["conversa_id"]
    r = client.post("/api/chat", json={"mensagem": "e agora?", "conversa_id": cid})
    assert r.status_code == 200 and len(db.messages_) == 4
