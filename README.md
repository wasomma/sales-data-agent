# Sales Data Agent

A Python CLI agent that answers natural-language questions about sales data
("List my top 10 largest deals for 2026") with exact, verifiable answers.

Excel and PowerPoint exports are ingested into a local DuckDB database; an
LLM agent translates questions into SQL, executes it read-only, and shows the
query alongside every answer.

**LLM backends** (picked automatically):

1. **Claude subscription (default)** — no API key needed. Drives headless
   Claude Code (`claude -p`), which uses your Claude login; the agent's tools
   are served to it via a local MCP server.
2. **Anthropic API** (`claude-opus-5`) — used when `ANTHROPIC_API_KEY` is set.
3. **Gemini** (planned) — drops into `src/sales_agent/llm.py` when the
   company-authorized key is available.

Force a backend with `SALES_AGENT_BACKEND=api|claude-code`. Until real data is
authorized, all testing uses **synthetic data**. See [DESIGN.md](DESIGN.md)
for the architecture and [CHANGELOG.md](CHANGELOG.md) for release history.

## Quick start

```bash
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
# No API key needed if Claude Code is installed and logged in.
# (Optional: copy .env.example to .env and set ANTHROPIC_API_KEY to use the API.)

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
| `src/sales_agent/llm.py` | API provider abstraction (ClaudeProvider now, GeminiProvider later) |
| `src/sales_agent/claude_code.py` | Subscription backend: headless Claude Code + MCP tools |
| `src/sales_agent/mcp_server.py` | MCP server exposing the tools over stdio |
| `src/sales_agent/agent.py` | Provider-agnostic tool loop; prints executed SQL |
| `src/sales_agent/cli.py` | Typer CLI: `generate-sample`, `sync`, `status`, `ask`, `chat` |

## Data safety

Company data never enters this repo: `data/`, spreadsheets, decks, DuckDB
files, and `.env` (API keys) are git-ignored. The agent's database connection
is read-only and restricted to single SELECT statements.
