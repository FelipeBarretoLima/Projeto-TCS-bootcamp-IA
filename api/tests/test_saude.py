from fastapi.testclient import TestClient

from api.main import app


def test_saude():
    r = TestClient(app).get("/api/saude")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
