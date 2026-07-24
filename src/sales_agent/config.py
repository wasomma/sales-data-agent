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
MAX_TOKENS = int(os.getenv("SALES_AGENT_MAX_TOKENS", "16000"))

# Hard caps for the SQL tool
SQL_ROW_LIMIT = 200


def ensure_dirs() -> None:
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
