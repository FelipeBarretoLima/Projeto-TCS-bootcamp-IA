"""Nos testes: nada de mapas reais, .pkl real, banco real (Supabase) nem login real."""

import pytest

from api import config
from api.autenticacao import usuario_atual
from api.dependencias import banco
from api.main import app
from api.tests.falsos import USUARIO, BancoFalso


@pytest.fixture(autouse=True)
def dir_privado(tmp_path, monkeypatch):
    """Nunca ler os mapas reais de data/privado nos testes: cada teste tem uma pasta vazia."""
    pasta = tmp_path / "privado"
    pasta.mkdir()
    monkeypatch.setattr(config, "DIR_PRIVADO", pasta)
    return pasta


@pytest.fixture(autouse=True)
def sem_modelo_real(tmp_path, monkeypatch):
    """Nunca usar o .pkl real nos testes: por padrão não há classificador."""
    monkeypatch.setattr(config, "CAMINHO_MODELO", tmp_path / "nao_existe.pkl")


@pytest.fixture(autouse=True)
def db():
    """Banco em memória e um usuário logado em todas as rotas."""
    falso = BancoFalso()
    app.dependency_overrides[banco] = lambda: falso
    app.dependency_overrides[usuario_atual] = lambda: USUARIO
    yield falso
    app.dependency_overrides.clear()


@pytest.fixture
def logado_como():
    def troca(usuario):
        app.dependency_overrides[usuario_atual] = lambda: usuario
    return troca
