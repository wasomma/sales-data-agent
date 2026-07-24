"""DuckDB schema and connection helpers."""

import duckdb

from .config import DB_PATH, ensure_dirs

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS deals (
    deal_key          TEXT NOT NULL,
    deal_name         TEXT,
    account           TEXT,
    amount            DECIMAL(18,2),
    close_date        DATE,
    stage             TEXT,
    owner             TEXT,
    forecast_category TEXT,
    as_of_date        DATE NOT NULL,
    source_file       TEXT NOT NULL,
    file_hash         TEXT NOT NULL
);

-- One row per (deal, snapshot date). The same deal can arrive from both an xlsx
-- export and a pptx table for the same date; spreadsheets are authoritative.
CREATE OR REPLACE VIEW deals_snapshots AS
SELECT * FROM deals
QUALIFY ROW_NUMBER() OVER (
    PARTITION BY deal_key, as_of_date
    ORDER BY CASE WHEN lower(source_file) LIKE '%.xlsx' THEN 0 ELSE 1 END
) = 1;

CREATE OR REPLACE VIEW deals_current AS
SELECT * FROM deals_snapshots
QUALIFY ROW_NUMBER() OVER (PARTITION BY deal_key ORDER BY as_of_date DESC) = 1;

CREATE TABLE IF NOT EXISTS ingest_log (
    ingested_at   TIMESTAMP DEFAULT current_timestamp,
    source_file   TEXT,
    file_hash     TEXT,
    as_of_date    DATE,
    rows_loaded   INTEGER,
    rows_rejected INTEGER
);

CREATE TABLE IF NOT EXISTS rejects (
    source_file TEXT,
    raw_row     JSON,
    reason      TEXT
);

CREATE TABLE IF NOT EXISTS slide_text (
    source_file  TEXT,
    slide_number INTEGER,
    text         TEXT,
    as_of_date   DATE
);
"""


def connect_rw() -> duckdb.DuckDBPyConnection:
    """Read-write connection; creates the schema on first use."""
    ensure_dirs()
    con = duckdb.connect(str(DB_PATH))
    con.execute(SCHEMA_SQL)
    return con


def connect_ro() -> duckdb.DuckDBPyConnection:
    """Read-only connection for the agent's SQL tool."""
    return duckdb.connect(str(DB_PATH), read_only=True)
