"""Agent-facing tools: schema description, read-only SQL, source listing.

These are provider-agnostic: each tool has a JSON-schema definition plus a plain
Python implementation, so any LLM provider (Claude now, Gemini later) can call them.
"""

import re
from typing import Any

from .config import SQL_ROW_LIMIT
from .db import connect_ro

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "get_schema",
        "description": (
            "Get the database schema: tables, columns, types, and the distinct values "
            "of low-cardinality columns (stage, owner, forecast_category). Call this "
            "before writing SQL so filters use real values."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "run_sql",
        "description": (
            "Execute a single read-only SELECT (or WITH...SELECT) statement against "
            f"DuckDB. Results are capped at {SQL_ROW_LIMIT} rows. Use the deals_current "
            "view for questions about the pipeline as it stands now; use the "
            "deals_snapshots view (filtering/grouping by as_of_date) for how things "
            "changed between snapshots. Avoid the raw deals table — it can contain "
            "duplicate rows when the same deal appears in multiple source files. On a "
            "SQL error the error text is returned so you can correct the query and retry."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "The SQL query to run."}},
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_sources",
        "description": (
            "List the ingested source files with their as_of dates and row counts — "
            "use to answer questions about data freshness or provenance."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
]

_SELECT_RE = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)


def get_schema() -> str:
    con = connect_ro()
    try:
        # NOTE: no parameterized queries here — DuckDB prepared statements against
        # information_schema deadlock inside the MCP server's worker thread.
        rows = con.execute(
            "SELECT table_name, column_name, data_type FROM information_schema.columns "
            "WHERE table_name IN ('deals_snapshots', 'deals_current', 'ingest_log', 'slide_text') "
            "ORDER BY table_name, ordinal_position"
        ).fetchall()
        by_table: dict[str, list[str]] = {}
        for table, col, dtype in rows:
            by_table.setdefault(table, []).append(f"{col} {dtype}")
        lines = [f"{table}({', '.join(cols)})" for table, cols in by_table.items()]

        lines.append("")
        lines.append("deals_current = latest snapshot per deal (use for 'as of now' questions).")
        lines.append("deals_snapshots = all snapshots, one row per (deal, as_of_date); "
                     "filter by as_of_date for point-in-time or change questions.")
        lines.append("")
        for col in ("stage", "owner", "forecast_category"):
            vals = [v for (v,) in con.execute(
                f"SELECT DISTINCT {col} FROM deals_current WHERE {col} IS NOT NULL ORDER BY 1"
            ).fetchall()]
            lines.append(f"Distinct {col}: {vals}")
        dates = [str(d) for (d,) in con.execute(
            "SELECT DISTINCT as_of_date FROM deals_snapshots ORDER BY 1").fetchall()]
        lines.append(f"Snapshot as_of_dates: {dates}")
        return "\n".join(lines)
    finally:
        con.close()


def run_sql(query: str) -> str:
    if not _SELECT_RE.match(query or ""):
        return "ERROR: only a single SELECT or WITH...SELECT statement is allowed."
    if ";" in query.rstrip().rstrip(";"):
        return "ERROR: multiple statements are not allowed."
    con = connect_ro()
    try:
        result = con.execute(query)
        columns = [d[0] for d in result.description]
        rows = result.fetchmany(SQL_ROW_LIMIT + 1)
        truncated = len(rows) > SQL_ROW_LIMIT
        rows = rows[:SQL_ROW_LIMIT]
        out = [" | ".join(columns)]
        out += [" | ".join("" if v is None else str(v) for v in r) for r in rows]
        if truncated:
            out.append(f"... truncated at {SQL_ROW_LIMIT} rows")
        out.append(f"({len(rows)} row(s))")
        return "\n".join(out)
    except Exception as e:  # surfaced verbatim so the model can self-correct
        return f"SQL ERROR: {e}"
    finally:
        con.close()


def list_sources() -> str:
    con = connect_ro()
    try:
        rows = con.execute(
            "SELECT source_file, as_of_date, rows_loaded, rows_rejected, ingested_at "
            "FROM ingest_log ORDER BY as_of_date, source_file"
        ).fetchall()
        if not rows:
            return "No files ingested yet. Run `sales sync` first."
        return "\n".join(
            f"{f} | as_of={a} | rows={n} | rejected={rej} | ingested={ts}"
            for f, a, n, rej, ts in rows
        )
    finally:
        con.close()


def execute_tool(name: str, tool_input: dict) -> str:
    if name == "get_schema":
        return get_schema()
    if name == "run_sql":
        return run_sql(tool_input.get("query", ""))
    if name == "list_sources":
        return list_sources()
    return f"ERROR: unknown tool {name!r}"
