"""API settings. The secrets come from the .env file at the root (outside git)."""

import os
import re
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

# The user's maps (people marked by them). The API only reads this folder, never writes to it.
PRIVATE_DIR = PROJECT_ROOT / "data" / "private"

# Trained classifier (python -m ml.train). Outside git; without it, outflows stay uncategorized.
MODEL_PATH = PROJECT_ROOT / "ml" / "modelos" / "svm_tfidf.pkl"
# Base labeled CSV (python -m ml.label), outside git: the retraining adds the users' corrections to it
BASE_TRAINING_PATH = PROJECT_ROOT / "ml" / "dados" / "transacoes_rotuladas.csv"

# compiled page (npm run build in frontend/): if it exists, the API also serves the page
FRONTEND_DIR = PROJECT_ROOT / "frontend" / "dist"

ACCEPTED_EXTENSIONS = frozenset({".pdf", ".csv"})
MAX_SIZE = 10 * 1024 * 1024  # 10 MB
DEFAULT_PSEUDONYM = "u01"  # pseudonym used by the parser; the real owner comes from the login

# --- database (Supabase) ---
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()


def _project_url() -> str:
    """https://<ref>.supabase.co: from .env or deduced from the DATABASE_URL user (postgres.<ref>)."""
    explicit = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    if explicit:
        return explicit
    m = re.search(r"://postgres\.([a-z0-9]+):", DATABASE_URL)
    return f"https://{m.group(1)}.supabase.co" if m else ""


# --- login (Supabase Auth) ---
SUPABASE_URL = _project_url()
SUPABASE_PUBLISHABLE_KEY = os.environ.get("SUPABASE_PUBLISHABLE_KEY", "").strip()

# --- original text of the transactions (not anonymized), stored encrypted in the database ---
# Fernet key. Generate it with: python -m api.cipher --nova-chave. The SAME key on every machine that
# uses the same database; losing it = the originals already saved no longer open (the screen shows the
# anonymized text). Empty: nothing original is saved.
ORIGINALS_KEY = os.environ.get("CHAVE_ORIGINAIS", "").strip()

# --- assistant (Gemini) ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
# measured on 2026-11-11 (same questions, 3 times): 3.5-flash-lite ~2.5 s and stable; 3.1-flash-lite
# reached 11-39 s and gave 503 ("high demand"). If the primary fails, the fallbacks are tried in order.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "").strip() or "gemini-3.5-flash-lite"
GEMINI_FALLBACK_MODELS = [m.strip() for m in os.environ.get(
    "GEMINI_MODELOS_RESERVA", "gemini-3.6-flash,gemini-3.1-flash-lite").split(",") if m.strip()]
# seconds to wait for each model before moving to the next one (no new attempts on the same one);
# a normal call takes 1-3 s
GEMINI_TIMEOUT = float(os.environ.get("GEMINI_TIMEOUT", "").strip() or 10)

# --- deployment ---
# domains the page may call the API from, comma separated (only if the page is at another
# address; served by the API itself or by the Vite proxy, it is not needed)
CORS_ORIGINS = [o.strip().rstrip("/") for o in os.environ.get("CORS_ORIGENS", "").split(",") if o.strip()]
