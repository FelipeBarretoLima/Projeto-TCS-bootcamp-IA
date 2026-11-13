"""Nos testes: nada de mapas reais, .pkl real, banco real (Supabase) nem login real."""

import pytest

from api import config
from api.auth import usuario_atual
from api.dependencies import abre_banco, banco
from api.rate_limit import LIMITE_CHAT, LIMITE_IMPORTACAO, LIMITE_TRANSCRICAO
from api.main import app
from api.tests.fakes import USUARIO, BancoFalso


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
    monkeypatch.setattr(config, "CAMINHO_TREINO_BASE", tmp_path / "nao_existe.csv")


@pytest.fixture(autouse=True)
def chave_originais(monkeypatch):
    """Chave de teste para o texto original: nunca a do .env."""
    from cryptography.fernet import Fernet

    chave = Fernet.generate_key().decode()
    monkeypatch.setattr(config, "CHAVE_ORIGINAIS", chave)
    return chave


@pytest.fixture(autouse=True)
def db():
    """Banco em memória e um usuário logado em todas as rotas."""
    from contextlib import nullcontext

    falso = BancoFalso()
    app.dependency_overrides[banco] = lambda: falso
    app.dependency_overrides[abre_banco] = lambda: (lambda: nullcontext(falso))
    app.dependency_overrides[usuario_atual] = lambda: USUARIO
    yield falso
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def retreino_no_banco_falso(db, monkeypatch):
    """Retreino com o banco falso e na hora (sem thread), para o teste ver o resultado."""
    from contextlib import nullcontext

    from api.services import retraining

    monkeypatch.setattr(retraining, "abre_banco", lambda: nullcontext(db))
    monkeypatch.setattr(retraining, "inicia_em_segundo_plano", lambda alvo: alvo())


@pytest.fixture
def logado_como():
    def troca(usuario):
        app.dependency_overrides[usuario_atual] = lambda: usuario
    return troca


@pytest.fixture(autouse=True)
def limites_zerados():
    """Cada teste começa sem usos contados no limite por usuário."""
    LIMITE_CHAT.zera()
    LIMITE_IMPORTACAO.zera()
    LIMITE_TRANSCRICAO.zera()
