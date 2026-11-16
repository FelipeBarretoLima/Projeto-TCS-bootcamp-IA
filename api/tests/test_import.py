"""Importing a statement saves it in the (fake) database of the logged-in user, without repeating transactions."""

from fastapi.testclient import TestClient

from api.auth import current_user
from api.main import app

from api.tests.fakes import OTHER_USER, USER

HEADER = "Data,Valor,Identificador,Descrição\n"


def _line(day, amount, n, desc="Compra no débito - PADARIA MODELO"):
    return f"{day},{amount},11111111-2222-4333-8444-{n:012d},{desc}\n"


def _upload(content: str, name="extrato.csv"):
    return TestClient(app).post("/api/extratos", files={"arquivo": (name, content.encode())})


def test_imports_and_saves_to_the_logged_in_user(db):
    r = _upload(HEADER + _line("02/01/2024", "-12.50", 1) + _line("03/01/2024", "-8.00", 2), "fatura jan.csv")
    assert r.status_code == 200
    g = r.json()["gravacao"]
    assert (g["gravadas"], g["repetidas"]) == (2, 0)
    [statement] = db.list_statements(USER.id)
    assert statement["nome_arquivo"] == "fatura jan.csv"
    assert len(db.transactions(USER.id)) == 2 and db.transactions(OTHER_USER.id) == []


def test_same_file_twice_gives_409(db):
    csv = HEADER + _line("02/01/2024", "-12.50", 1)
    assert _upload(csv).status_code == 200
    r = _upload(csv)
    assert r.status_code == 409
    assert len(db.transactions(USER.id)) == 1


def test_overlapping_statements_do_not_duplicate_but_genuinely_equal_purchases_go_in(db):
    # statement A: two equal purchases on the same day (two real ones)
    a = HEADER + _line("02/01/2024", "-8.94", 1) + _line("02/01/2024", "-8.94", 2)
    # statement B overlaps: the same two + a third equal one + a new one
    b = (HEADER + _line("02/01/2024", "-8.94", 3) + _line("02/01/2024", "-8.94", 4)
         + _line("02/01/2024", "-8.94", 5) + _line("05/01/2024", "-30.00", 6))
    assert _upload(a, "a.csv").json()["gravacao"]["gravadas"] == 2
    g = _upload(b, "b.csv").json()["gravacao"]
    assert (g["gravadas"], g["repetidas"]) == (2, 2)
    assert len(db.transactions(USER.id)) == 4


def test_rejected_statement_is_not_saved(db):
    r = _upload("a,b,c\n1,2,3\n", "planilha.csv")
    assert r.status_code == 200
    assert r.json()["gravacao"] is None
    assert db.list_statements(USER.id) == []


def test_deletes_statement_and_its_transactions(db, logged_in_as):
    sid = _upload(HEADER + _line("02/01/2024", "-12.50", 1)).json()["gravacao"]["extrato_id"]
    client = TestClient(app)
    logged_in_as(OTHER_USER)
    assert client.delete(f"/api/extratos/{sid}").status_code == 404  # not theirs
    logged_in_as(USER)
    assert client.delete(f"/api/extratos/{sid}").status_code == 204
    assert db.transactions(USER.id) == [] and client.get("/api/extratos").json() == []


def test_deleting_a_statement_keeps_what_another_statement_also_brought(db):
    client = TestClient(app)
    a = HEADER + _line("02/01/2024", "-8.94", 1) + _line("03/01/2024", "-20.00", 2)
    b = HEADER + _line("03/01/2024", "-20.00", 3) + _line("05/01/2024", "-30.00", 4)  # repeats day 3
    sa = _upload(a, "a.csv").json()["gravacao"]["extrato_id"]
    sb = _upload(b, "b.csv").json()["gravacao"]["extrato_id"]
    assert client.delete(f"/api/extratos/{sa}").status_code == 204
    # day 3 was also in statement b: it stays in the account, now as a transaction of b
    assert sorted(t["data"].day for t in db.transactions(USER.id)) == [3, 5]
    [remaining] = client.get("/api/extratos").json()
    assert remaining["id"] == sb and remaining["linhas_gravadas"] == 2
    assert client.delete(f"/api/extratos/{sb}").status_code == 204
    assert db.transactions(USER.id) == []


def test_without_login_gives_401():
    app.dependency_overrides.pop(current_user)
    client = TestClient(app)
    assert client.get("/api/extratos").status_code == 401
    assert client.get("/api/painel", headers={"Authorization": "Basic abc"}).status_code == 401
