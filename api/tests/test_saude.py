from fastapi.testclient import TestClient

from api.main import app


def test_saude():
    r = TestClient(app).get("/api/saude")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_config_publica_nunca_expoe_a_chave_secreta(monkeypatch):
    from api import config

    monkeypatch.setattr(config, "SUPABASE_URL", "https://exemplo.supabase.co")
    monkeypatch.setattr(config, "SUPABASE_PUBLISHABLE_KEY", "sb_publishable_teste")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_nao_pode_sair")
    r = TestClient(app).get("/api/config")
    assert r.json() == {"supabase_url": "https://exemplo.supabase.co",
                        "supabase_publishable_key": "sb_publishable_teste"}
    assert "sb_secret" not in r.text
