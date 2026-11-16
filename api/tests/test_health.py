from fastapi.testclient import TestClient

from api.main import app


def test_health():
    r = TestClient(app).get("/api/saude")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_public_config_never_exposes_the_secret_key(monkeypatch):
    from api import config

    monkeypatch.setattr(config, "SUPABASE_URL", "https://exemplo.supabase.co")
    monkeypatch.setattr(config, "SUPABASE_PUBLISHABLE_KEY", "sb_publishable_teste")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_nao_pode_sair")
    r = TestClient(app).get("/api/config")
    assert r.json() == {"supabase_url": "https://exemplo.supabase.co",
                        "supabase_publishable_key": "sb_publishable_teste"}
    assert "sb_secret" not in r.text


def test_logout_removes_the_token_from_the_cache():
    import time

    from api import auth

    auth._cache["tok"] = (time.monotonic() + 60, object())
    r = TestClient(app).delete("/api/sessao", headers={"Authorization": "Bearer tok"})
    assert r.status_code == 204 and "tok" not in auth._cache
    assert TestClient(app).delete("/api/sessao").status_code == 204  # no token: does nothing
