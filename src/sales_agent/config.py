"""Central configuration: paths, model selection, mapping file location."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = Path(os.getenv("SALES_AGENT_DATA_DIR", PROJECT_ROOT / "data"))
INBOX_DIR = DATA_DIR / "inbox"
DB_PATH = DATA_DIR / "sales.duckdb"
MAPPING_PATH = PROJECT_ROOT / "mapping.yaml"

MODEL = os.getenv("SALES_AGENT_MODEL", "claude-opus-5")
# Gemini via the API key, used when SALES_AGENT_PROVIDER=gemini. Distinct from
# SALES_AGENT_AGY_MODEL, which names a model inside the Antigravity tenant.
# Note "-preview": bare gemini-3.1-pro is a 404 on the Gemini Developer API.
# Preview ids do get retired, so if this starts 404ing, gemini-pro-latest is the
# stable-alias fallback.
GEMINI_MODEL = os.getenv("SALES_AGENT_GEMINI_MODEL", "gemini-3.1-pro-preview")
MAX_TOKENS = int(os.getenv("SALES_AGENT_MAX_TOKENS", "16000"))

# Hard caps for the SQL tool
SQL_ROW_LIMIT = 200


def ensure_dirs() -> None:
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
