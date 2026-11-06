import pytest

from api import config


@pytest.fixture(autouse=True)
def dir_privado(tmp_path, monkeypatch):
    """Nunca ler os mapas reais de data/privado nos testes: cada teste tem uma pasta vazia."""
    pasta = tmp_path / "privado"
    pasta.mkdir()
    monkeypatch.setattr(config, "DIR_PRIVADO", pasta)
    return pasta
