"""A body that is too large is refused before FastAPI reads the upload (which it reads before the login)."""

from fastapi.testclient import TestClient

from api import config
from api.auth import current_user
from api.main import app

LARGE = config.MAX_SIZE + 128 * 1024


def _without_login():
    app.dependency_overrides.pop(current_user, None)  # conftest logs a user in on every route
    return TestClient(app)


def test_large_body_with_content_length_is_refused_without_login(db):
    r = _without_login().post("/api/extratos", files={"arquivo": ("e.csv", b"x" * LARGE, "text/csv")})
    assert r.status_code == 413 and r.json()["detail"] == "arquivo maior que 10 MB"
    assert db.statements == {}


def test_large_body_sent_in_chunks_is_refused(db):
    def chunks():  # without Content-Length (transfer-encoding: chunked)
        for _ in range(LARGE // (64 * 1024) + 1):
            yield b"x" * (64 * 1024)

    r = _without_login().post("/api/extratos", content=chunks(),
                              headers={"content-type": "multipart/form-data; boundary=abc"})
    assert r.status_code == 413
    assert db.statements == {}


def test_normal_body_still_goes_through():
    # without login, the small body reaches the token check (401), not the limit
    r = _without_login().post("/api/extratos", files={"arquivo": ("e.csv", b"Data,Valor\n", "text/csv")})
    assert r.status_code == 401
