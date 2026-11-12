"""Corpo grande demais é recusado antes de o FastAPI ler o upload (que ele lê antes do login)."""

from fastapi.testclient import TestClient

from api import config
from api.auth import usuario_atual
from api.main import app

GRANDE = config.TAMANHO_MAXIMO + 128 * 1024


def _sem_login():
    app.dependency_overrides.pop(usuario_atual, None)  # o conftest loga um usuário em todas as rotas
    return TestClient(app)


def test_corpo_grande_com_content_length_e_recusado_sem_login(db):
    r = _sem_login().post("/api/extratos", files={"arquivo": ("e.csv", b"x" * GRANDE, "text/csv")})
    assert r.status_code == 413 and r.json()["detail"] == "arquivo maior que 10 MB"
    assert db.extratos == {}


def test_corpo_grande_enviado_em_pedacos_e_recusado(db):
    def pedacos():  # sem Content-Length (transfer-encoding: chunked)
        for _ in range(GRANDE // (64 * 1024) + 1):
            yield b"x" * (64 * 1024)

    r = _sem_login().post("/api/extratos", content=pedacos(),
                          headers={"content-type": "multipart/form-data; boundary=abc"})
    assert r.status_code == 413
    assert db.extratos == {}


def test_corpo_normal_continua_passando():
    # sem login, o corpo pequeno chega até a conferência do token (401), não ao limite
    r = _sem_login().post("/api/extratos", files={"arquivo": ("e.csv", b"Data,Valor\n", "text/csv")})
    assert r.status_code == 401
