# Sales Data Agent — Design Document

**Status:** Draft v2 — 2026-07-24
**Owner:** wasomma@gmail.com

> **v2 change:** The company Gemini API key is not yet available. Phase 1 uses the
> **Claude API** (`claude-opus-5`) behind a thin provider abstraction, and tests
> against **synthetic sales data** only. When the Gemini key arrives, a
> `GeminiProvider` drops in and real exports replace the synthetic files.
> No company data is sent to any API until then.

## 1. Summary

A Python CLI agent that answers natural-language questions about company sales data
("List my top 10 largest deals for 2026", "How many deals are forecasted for 2026 in
account X") with exact, verifiable answers.

Sales data arrives as Excel spreadsheets and PowerPoint decks exported from the CRM.
An ingestion pipeline normalizes them into a local DuckDB database; a Gemini-powered
agent translates questions into SQL, executes it, and explains the results.

**Key decision — this is *not* a classic RAG system.** Questions about sales data are
predominantly aggregations (top-N, counts, sums, filters by year/account). Vector
retrieval returns "similar chunks" and can silently miss the row that is actually #1.
Text-to-SQL over a structured store answers these exactly. RAG is deferred to a later
phase, scoped only to the *narrative* content of decks (positioning, commentary),
where it is the right tool.

## 2. Goals and non-goals

### Goals
- Ask questions in plain English from a terminal; get correct numbers with the SQL shown.
- Ingest `.xlsx` and `.pptx` files from a watched local folder with one command.
- Handle frequently changing files: re-ingestion is idempotent, and history is kept as
  snapshots so "how did the forecast change?" is answerable later.
- Single-user, local-first. The only network dependency is the Gemini API
  (authorized for this data by the business).

### Non-goals (for now)
- CRM API integration — no API access is available; file exports are the source of truth.
- Cloud storage sync (SharePoint/Drive) — Phase 2.
- Multi-user access, web UI, Slack bot — revisit after the CLI proves value.
- Write access to any source data. The agent is strictly read-only.

## 3. Architecture

```
┌────────────────────┐
│  ./data/inbox/     │   Excel + PowerPoint exports, dropped in manually
└─────────┬──────────┘
          │  `sales sync`
          ▼
┌────────────────────┐
│  Ingestion layer   │   parse → normalize → validate → snapshot
│  (pandas, openpyxl,│
│   python-pptx)     │
└─────────┬──────────┘
          ▼
┌────────────────────┐
│  DuckDB            │   ./data/sales.duckdb  (single file)
│  deals / snapshots │
│  / ingest_log      │
└─────────┬──────────┘
          │  read-only connection
          ▼
┌────────────────────┐        ┌──────────────┐
│  CLI agent loop    │ ◄────► │  Gemini API  │
│  (Typer + Rich)    │  tools │  (function   │
│  `sales chat`      │        │   calling)   │
└────────────────────┘        └──────────────┘
```

Three decoupled parts — ingestion, storage, agent — so any one can be swapped later
(e.g., cloud sync replacing the inbox folder, or a web UI replacing the CLI) without
touching the others.

## 4. Ingestion layer

### 4.1 Inputs
- `./data/inbox/` — the drop folder. `sales sync` scans it, ingests new/changed files
  (detected by content hash), and records each run in `ingest_log`.
- `.xlsx`: read with pandas/openpyxl. Multi-sheet workbooks: each sheet is matched
  against the column-mapping config; unmatched sheets are skipped with a warning.
- `.pptx`: read with python-pptx. Phase 1 extracts **tables** embedded in slides only.
  Slide narrative text is stored raw (for the future RAG phase) but not parsed.

### 4.2 Normalization
Formats are consistent across files, so mapping is **config-driven, not LLM-driven** —
deterministic, free, and debuggable. A `mapping.yaml` declares how source columns map
to the canonical schema:

```yaml
# mapping.yaml (illustrative)
column_aliases:
  deal_name:   ["Deal", "Opportunity Name", "Deal Name"]
  account:     ["Account", "Customer", "Account Name"]
  amount:      ["Amount", "Deal Value", "ACV ($)"]
  close_date:  ["Close Date", "Expected Close"]
  stage:       ["Stage", "Sales Stage"]
  owner:       ["Owner", "Rep", "Account Executive"]
```

Validation on ingest: amounts coerced to numeric, dates parsed, rows failing
validation quarantined to a `rejects` table with a reason — never silently dropped.

### 4.3 Snapshots (handling frequently changing files)
Exports are point-in-time copies of a living CRM, so ingestion **appends snapshots**
rather than overwriting:

- Every ingested row carries `source_file`, `file_hash`, and `as_of_date`
  (from the filename, file metadata, or an in-file "report date" cell — in that
  priority order; configurable).
- A `deals_current` **view** exposes only the latest snapshot per deal, so everyday
  queries are simple ("top deals" means top deals *now*).
- The full history stays queryable: "which deals slipped from Q3 to Q4 since last
  month's export?" becomes a self-join across snapshots.
- Re-running `sync` on unchanged files is a no-op (hash match) — idempotent by design.

## 5. Data model (DuckDB)

```sql
CREATE TABLE deals (
    deal_key      TEXT,      -- stable identity: CRM id if present, else hash(account, deal_name)
    deal_name     TEXT,
    account       TEXT,
    amount        DECIMAL(18,2),
    close_date    DATE,
    stage         TEXT,
    owner         TEXT,
    forecast_category TEXT,  -- if present in exports (commit / best case / pipeline)
    as_of_date    DATE NOT NULL,
    source_file   TEXT NOT NULL,
    file_hash     TEXT NOT NULL
);

CREATE VIEW deals_current AS
SELECT * FROM deals
QUALIFY ROW_NUMBER() OVER (PARTITION BY deal_key ORDER BY as_of_date DESC) = 1;

CREATE TABLE ingest_log (
    ingested_at   TIMESTAMP,
    source_file   TEXT,
    file_hash     TEXT,
    rows_loaded   INTEGER,
    rows_rejected INTEGER
);

CREATE TABLE rejects (
    source_file   TEXT,
    raw_row       JSON,
    reason        TEXT
);

-- Raw slide text, stored now, used in the RAG phase later
CREATE TABLE slide_text (
    source_file   TEXT,
    slide_number  INTEGER,
    text          TEXT,
    as_of_date    DATE
);
```

Why DuckDB: analytical SQL engine in a single local file, no server, excellent pandas
interop, and fast far beyond this data volume. If multi-user access is ever needed,
the schema ports to Postgres nearly unchanged.

## 6. Agent layer

### 6.1 Interaction
`sales chat` starts a REPL (Typer + Rich). One-shot mode also supported:
`sales ask "top 10 largest deals for 2026"`.

### 6.2 Model
The agent talks to the LLM through a small **provider interface** (`llm.py`): the
provider receives the conversation + tool definitions and returns either tool calls
or a final answer. Two implementations:

- **ClaudeProvider (current)** — Anthropic SDK, model `claude-opus-5` (configurable
  via `SALES_AGENT_MODEL`), native tool use. Used for all development against
  synthetic data.
- **GeminiProvider (later)** — Gemini function calling via the business-authorized
  key, added when access is granted. Only this file changes; tools, ingestion, and
  CLI are provider-agnostic.

### 6.3 Tools exposed to the model

| Tool | Purpose |
|---|---|
| `get_schema()` | Tables, columns, types, plus distinct values for low-cardinality columns (stage, owner, forecast_category) so the model filters by real values, not guesses. |
| `run_sql(query)` | Execute a `SELECT` against a **read-only** DuckDB connection. Returns rows (capped, e.g. 200) or the DB error verbatim so the model can self-correct. |
| `list_sources()` | Ingested files, their `as_of_date`s, row counts — lets the agent answer "how fresh is this data?" |

Loop: question → model calls tools (typically `get_schema` once, then `run_sql`,
retrying on SQL errors) → model summarizes actual results.

### 6.4 Trust and guardrails
- **Show the SQL.** Every answer prints the executed query in a dim panel. With sales
  numbers, verifiability is the difference between a toy and a tool.
- Read-only connection (`duckdb.connect(readonly=True)`) — enforced by the engine,
  not by prompt. Single-statement `SELECT`s only, statement timeout, row cap.
- The system prompt instructs: answer only from query results; if the data can't
  answer the question, say so — never estimate from general knowledge.
- Data sent to Gemini: schema, distinct filter values, and query *results* for the
  question asked — bounded and authorized, but worth stating in security review.

## 7. Phases

### Phase 1 — prove the value chain  *(scope of first build)*
Inbox folder → ingest → DuckDB → `sales chat` answering aggregate questions
correctly, SQL shown. A deterministic **synthetic data generator**
(`sales generate-sample`) produces realistic pipeline exports — two Excel snapshots
with drift between them plus a QBR deck with an embedded table — so the whole chain
is testable end-to-end with zero company data. Exit criteria: the two motivating
example questions answered correctly against the synthetic dataset (and later,
against real exports once the Gemini key + data authorization are in place).

### Phase 2 — freshness and history
Cloud-storage sync (Microsoft Graph and/or Drive API, delta queries) replacing the
manual inbox; scheduled sync; snapshot-comparison questions ("what changed since
last week?") as a first-class capability.

### Phase 3 — narrative and reach
RAG over `slide_text` (Gemini embeddings + DuckDB VSS extension), with a
`search_documents` tool the agent routes qualitative questions to. Optionally a
shared interface (web or Slack) if the team wants access.

## 8. Tech stack

| Concern | Choice |
|---|---|
| Language | Python 3.12+ |
| CLI | Typer + Rich |
| Excel parsing | pandas + openpyxl |
| PowerPoint parsing | python-pptx |
| Database | DuckDB |
| LLM | Claude API (`anthropic` SDK, `claude-opus-5`) now; Gemini API later via provider swap |
| Config | `mapping.yaml` + `.env` for the API key (git-ignored) |
| Tests | pytest; golden-file tests for ingestion, canned Q→SQL cases for the agent |

## 9. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Model writes wrong SQL | Show SQL on every answer; feed DB errors back for self-correction; build a small eval set of known Q→A pairs from real data. |
| Deal identity unstable across exports (no CRM id) | `deal_key` falls back to hash(account, deal_name); renamed deals appear as new — documented limitation until a CRM id column can be added to exports. |
| Column drift in future exports | Unmatched columns fail loudly at ingest with a diff against `mapping.yaml`; fixing is a one-line config edit. |
| `as_of_date` inferred wrongly | Priority order is configurable; `list_sources()` makes the inferred dates visible for audit. |
| PPTX tables are messy (merged cells, images of tables) | Phase 1 treats PPTX as best-effort; spreadsheets are the authoritative numbers source. Images of tables are out of scope. |

## 10. Open questions

1. Do exports contain a CRM deal id column? (Greatly improves snapshot linking — worth
   adding to the export template if possible.)
2. Where does `as_of_date` reliably live — filename convention, or a cell in the file?
3. Rough monthly volume of files/rows? (Almost certainly trivial for DuckDB, but
   informs whether `sync` needs progress reporting.)
4. Any fields in the exports that should *not* be sent to Gemini even though the
   dataset is broadly authorized (e.g., personal contact details)? A column-level
   exclusion list in `mapping.yaml` is cheap to add up front.
