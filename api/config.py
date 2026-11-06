"""Configurações da API."""

from pathlib import Path

RAIZ_PROJETO = Path(__file__).resolve().parents[1]

# Mapas do usuário (pessoas marcadas). A API só lê esta pasta, nunca grava nela.
DIR_PRIVADO = RAIZ_PROJETO / "data" / "privado"

EXTENSOES_ACEITAS = frozenset({".pdf", ".csv"})
TAMANHO_MAXIMO = 10 * 1024 * 1024  # 10 MB
USUARIO_PADRAO = "u01"
