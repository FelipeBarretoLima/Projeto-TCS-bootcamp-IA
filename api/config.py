"""Configurações da API. Os segredos vêm do arquivo .env na raiz (fora do git)."""

import os
import re
from pathlib import Path

from dotenv import load_dotenv

RAIZ_PROJETO = Path(__file__).resolve().parents[1]
load_dotenv(RAIZ_PROJETO / ".env")

# Mapas do usuário (pessoas marcadas). A API só lê esta pasta, nunca grava nela.
DIR_PRIVADO = RAIZ_PROJETO / "data" / "privado"

# Classificador treinado (python -m ml.treinar). Fora do git; sem ele, as saídas ficam sem categoria.
CAMINHO_MODELO = RAIZ_PROJETO / "ml" / "modelos" / "svm_tfidf.pkl"

EXTENSOES_ACEITAS = frozenset({".pdf", ".csv"})
TAMANHO_MAXIMO = 10 * 1024 * 1024  # 10 MB
USUARIO_PADRAO = "u01"  # pseudônimo usado pelo parser; o dono real vem do login

# --- banco (Supabase) ---
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()


def _url_do_projeto() -> str:
    """https://<ref>.supabase.co: do .env ou deduzido do usuário do DATABASE_URL (postgres.<ref>)."""
    explicita = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    if explicita:
        return explicita
    m = re.search(r"://postgres\.([a-z0-9]+):", DATABASE_URL)
    return f"https://{m.group(1)}.supabase.co" if m else ""


# --- login (Supabase Auth) ---
SUPABASE_URL = _url_do_projeto()
SUPABASE_PUBLISHABLE_KEY = os.environ.get("SUPABASE_PUBLISHABLE_KEY", "").strip()

# --- texto original das transações (sem anonimizar), guardado cifrado no banco ---
# Chave Fernet. Gere com: python -m api.cifra --nova-chave. A MESMA chave em todas as máquinas que
# usam o mesmo banco; perdê-la = os originais já gravados não abrem mais (a tela mostra o anonimizado).
# Vazia: nada original é gravado.
CHAVE_ORIGINAIS = os.environ.get("CHAVE_ORIGINAIS", "").strip()

# --- assistente (Gemini) ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "").strip() or "gemini-3.1-flash-lite"
