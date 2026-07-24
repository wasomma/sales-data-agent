# Sales Data Agent

A Python CLI agent that answers natural-language questions about sales data
("List my top 10 largest deals for 2026") with exact, verifiable answers.

Excel and PowerPoint exports are ingested into a local DuckDB database; an
LLM agent translates questions into SQL, executes it read-only, and shows the
query alongside every answer.

**Current LLM:** Claude (`claude-opus-5`) behind a provider abstraction —
swapping to the company-authorized Gemini API later means changing only
`src/sales_agent/llm.py`. Until then, all testing uses **synthetic data**; no
company data is sent to any API. See [DESIGN.md](DESIGN.md) for the full
architecture.

## Quick start

```bash
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
copy .env.example .env      # then put your ANTHROPIC_API_KEY in .env

.venv\Scripts\sales generate-sample   # writes synthetic exports to data/inbox
.venv\Scripts\sales sync              # ingests them into DuckDB
.venv\Scripts\sales ask "What are my top 10 largest deals closing in 2026?"
.venv\Scripts\sales chat              # interactive session
```

`sales status` lists ingested files; `sales sync` is idempotent (unchanged
files are skipped by content hash). To use real exports later, drop them into
`data/inbox/` — column-header variations are handled via `mapping.yaml`.

## Layout

| Path | What it is |
|---|---|
| `src/sales_agent/ingest.py` | xlsx/pptx parsing, normalization, snapshot ingestion |
| `src/sales_agent/db.py` | DuckDB schema: `deals` + deduped `deals_snapshots` / `deals_current` views |
| `src/sales_agent/generate.py` | Deterministic synthetic dataset (two snapshots + QBR deck) |
| `src/sales_agent/tools.py` | Agent tools: `get_schema`, `run_sql` (read-only), `list_sources` |
| `src/sales_agent/llm.py` | Provider abstraction (ClaudeProvider now, GeminiProvider later) |
| `src/sales_agent/agent.py` | Provider-agnostic tool loop; prints executed SQL |
| `src/sales_agent/cli.py` | Typer CLI: `generate-sample`, `sync`, `status`, `ask`, `chat` |

## Data safety

Company data never enters this repo: `data/`, spreadsheets, decks, DuckDB
files, and `.env` (API keys) are git-ignored. The agent's database connection
is read-only and restricted to single SELECT statements.
