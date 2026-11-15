"""In the tests: no real maps, no real .pkl, no real database (Supabase) and no real login."""

import pytest

from api import config
from api.auth import current_user
from api.dependencies import database, open_database
from api.rate_limit import CHAT_LIMIT, IMPORT_LIMIT
from api.main import app
from api.tests.fakes import USER, FakeDatabase


@pytest.fixture(autouse=True)
def private_dir(tmp_path, monkeypatch):
    """Never read the real maps of data/private in the tests: each test has an empty folder."""
    folder = tmp_path / "privado"
    folder.mkdir()
    monkeypatch.setattr(config, "PRIVATE_DIR", folder)
    return folder


@pytest.fixture(autouse=True)
def no_real_model(tmp_path, monkeypatch):
    """Never use the real .pkl in the tests: by default there is no classifier."""
    monkeypatch.setattr(config, "MODEL_PATH", tmp_path / "nao_existe.pkl")
    monkeypatch.setattr(config, "BASE_TRAINING_PATH", tmp_path / "nao_existe.csv")


@pytest.fixture(autouse=True)
def originals_key(monkeypatch):
    """Test key for the original text: never the one from .env."""
    from cryptography.fernet import Fernet

    key = Fernet.generate_key().decode()
    monkeypatch.setattr(config, "ORIGINALS_KEY", key)
    return key


@pytest.fixture(autouse=True)
def db():
    """In-memory database and a logged-in user on every route."""
    from contextlib import nullcontext

    fake = FakeDatabase()
    app.dependency_overrides[database] = lambda: fake
    app.dependency_overrides[open_database] = lambda: (lambda: nullcontext(fake))
    app.dependency_overrides[current_user] = lambda: USER
    yield fake
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def retraining_on_fake_database(db, monkeypatch):
    """Retraining with the fake database and right away (no thread), so the test sees the result."""
    from contextlib import nullcontext

    from api.services import retraining

    monkeypatch.setattr(retraining, "open_database", lambda: nullcontext(db))
    monkeypatch.setattr(retraining, "start_in_background", lambda target: target())


@pytest.fixture
def logged_in_as():
    def switch(user):
        app.dependency_overrides[current_user] = lambda: user
    return switch


@pytest.fixture(autouse=True)
def limits_reset():
    """Each test starts with no uses counted in the per-user limit."""
    CHAT_LIMIT.reset()
    IMPORT_LIMIT.reset()
