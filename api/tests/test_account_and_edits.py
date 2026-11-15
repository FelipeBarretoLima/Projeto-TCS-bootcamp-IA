"""Fixing a category, renaming a conversation, profile, deleting the account, dashboard month and usage limit."""

from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from agent.assistant import Answer
from api.dependencies import assistant_model
from api.rate_limit import RateLimit
from api.main import app
from api.routes import assistant as assistant_route
from api.tests.fakes import OTHER_USER, USER

HEADER = "Data,Valor,Identificador,Descrição\n"


def _import(client, lines):
    csv = HEADER + "".join(f"{d},{v},11111111-2222-4333-8444-{n:012d},Compra no débito - PADARIA MODELO\n"
                           for n, (d, v) in enumerate(lines, 1))
    r = client.post("/api/extratos", files={"arquivo": ("e.csv", csv.encode())})
    assert r.status_code == 200
    return r


def test_fixing_a_category_only_applies_to_the_owner(db, logged_in_as):
    client = TestClient(app)
    _import(client, [("02/01/2024", "-12.50")])
    [t] = client.get("/api/transacoes").json()

    assert client.patch(f"/api/transacoes/{t['id']}", json={"categoria": "lazer"}).status_code == 400
    assert client.patch(f"/api/transacoes/{t['id']}", json={"categoria": "mercado"}).status_code == 204
    assert client.get("/api/transacoes").json()[0]["categoria"] == "mercado"
    assert db.rows[0]["origem_categoria"] == "usuario"

    assert client.patch(f"/api/transacoes/{t['id']}", json={"categoria": None}).status_code == 204
    assert db.rows[0]["categoria"] is None and db.rows[0]["origem_categoria"] is None

    logged_in_as(OTHER_USER)
    assert client.patch(f"/api/transacoes/{t['id']}", json={"categoria": "mercado"}).status_code == 404


def test_rename_conversation(db, logged_in_as):
    client = TestClient(app)
    cid = db.create_conversation(USER.id, "antigo")
    assert client.patch(f"/api/conversas/{cid}", json={"titulo": "   "}).status_code == 400
    assert client.patch(f"/api/conversas/{cid}", json={"titulo": " Gastos de março "}).status_code == 204
    assert client.get("/api/conversas").json()[0]["titulo"] == "Gastos de março"
    logged_in_as(OTHER_USER)
    assert client.patch(f"/api/conversas/{cid}", json={"titulo": "x"}).status_code == 404


def test_change_profile_name(db):
    client = TestClient(app)
    r = client.patch("/api/perfil", json={"nome": " Maria "})
    assert r.status_code == 200 and r.json() == {"nome": "Maria", "email": USER.email}
    assert db.users[USER.id]["nome"] == "Maria"
    assert client.patch("/api/perfil", json={"nome": "  "}).status_code == 400


def test_deleting_the_account_deletes_everything_of_the_user_and_nothing_of_others(db, logged_in_as):
    client = TestClient(app)
    _import(client, [("02/01/2024", "-12.50")])
    db.create_conversation(USER.id, "minha")
    logged_in_as(OTHER_USER)
    _import(client, [("03/01/2024", "-1.00")])
    logged_in_as(USER)

    assert client.delete("/api/conta").status_code == 204
    assert db.transactions(USER.id) == [] and db.list_statements(USER.id) == []
    assert db.list_conversations(USER.id) == []
    assert len(db.transactions(OTHER_USER.id)) == 1


def test_dashboard_of_a_chosen_month(db):
    client = TestClient(app)
    for day, amount in ((date(2024, 1, 5), "-100.00"), (date(2024, 3, 5), "-30.00")):
        db.rows.append({"usuario_id": USER.id, "extrato_id": None, "data": day, "historico": "X",
                        "contraparte": "LOJA", "valor": Decimal(amount), "tipo": "saida", "meio": "pix",
                        "banco": "b", "categoria": "compras", "origem_categoria": "regra"})
    default = client.get("/api/painel").json()
    assert default["mes_valor"] == "2024-03" and default["despesas"] == 30.0
    assert [m["valor"] for m in default["meses"]] == ["2024-03", "2024-01"]
    january = client.get("/api/painel?mes=2024-01").json()
    assert january["mes"] == "jan/24" and january["despesas"] == 100.0
    assert january["grafico"]["rotulos"][-1] == "jan/24"  # the 6 months end in the chosen month
    assert client.get("/api/painel?mes=2024-13").status_code == 400


def test_chat_question_limit(monkeypatch):
    app.dependency_overrides[assistant_model] = lambda: object()
    monkeypatch.setattr(assistant_route, "answer", lambda *a, **k: Answer("ok", None))
    client = TestClient(app)
    statuses = [client.post("/api/chat", json={"mensagem": "oi"}).status_code for _ in range(11)]
    assert statuses[:10] == [200] * 10
    assert statuses[10] == 429


def test_limit_frees_up_after_the_window(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr("api.rate_limit.time.monotonic", lambda: now[0])
    limit = RateLimit(2, 60, "testes")
    limit.check("u")
    limit.check("u")
    try:
        limit.check("u")
        raise AssertionError("deveria ter barrado")
    except Exception as e:
        assert getattr(e, "status_code", None) == 429
    limit.check("outro")  # each user has their own count
    now[0] += 61
    limit.check("u")


def test_deleting_the_account_forgets_its_tokens_on_other_devices():
    from api import auth

    never_expires = float("inf")
    auth._cache.update({"aparelho-a": (never_expires, USER), "aparelho-b": (never_expires, USER),
                        "de-outra-pessoa": (never_expires, OTHER_USER)})
    try:
        assert TestClient(app).delete("/api/conta").status_code == 204
        assert set(auth._cache) == {"de-outra-pessoa"}
    finally:
        auth._cache.clear()
