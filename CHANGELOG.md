# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/). Each release is a git tag (`v0.x.y`)
pointing at the push that shipped it.

## [0.3.1] - 2026-07-24

### Added
- `sample-data/` folder with committed reference copies of the synthetic
  dataset (two pipeline snapshots + QBR deck) for easy viewing and demos. The
  agent does not read this folder; `data/inbox/` remains the git-ignored
  ingestion path for real data. Narrow `.gitignore` exceptions added for
  `sample-data/*.xlsx` and `sample-data/*.pptx` only, with a warning README.

## [0.3.0] - 2026-07-24

### Added
- **Claude subscription support — no API key needed.** New `ClaudeCodeBackend`
  (`claude_code.py`) drives headless Claude Code (`claude -p`), which runs on the
  Claude subscription login. Selected automatically when `ANTHROPIC_API_KEY` is
  not set; override with `SALES_AGENT_BACKEND=api|claude-code`.
- MCP server (`mcp_server.py`, `python -m sales_agent.mcp_server`) exposing
  `get_schema`, `run_sql`, and `list_sources` over stdio — this is how Claude
  Code reaches the database. Executed SQL is still shown for every answer by
  parsing Claude Code's streamed JSON events.
- This changelog; releases are now tagged in git.

### Fixed
- `get_schema` deadlocked when called through the MCP server: DuckDB prepared
  statements against `information_schema` hang inside the MCP worker thread.
  Rewritten as a single non-parameterized query.
- Claude Code can hang on MCP-server shutdown; the backend now finishes as soon
  as the result event arrives instead of waiting for process exit, and surfaces
  plain-text CLI errors instead of swallowing them.

### Verified
- End-to-end on a live subscription: "top 5 largest deals closing in 2026"
  answered correctly against the synthetic dataset, SQL displayed.

## [0.2.0] - 2026-07-24

### Added
- Phase 1 scaffold: snapshot-based ingestion (`.xlsx` via pandas, `.pptx` tables
  and narrative text via python-pptx), DuckDB schema, config-driven column
  mapping (`mapping.yaml`), rejects quarantine, idempotent `sync` by content hash.
- Deterministic synthetic data generator (`sales generate-sample`): two pipeline
  snapshots (2026-06-30, 2026-07-21) with realistic drift, plus a QBR deck with
  an embedded top-deals table.
- Provider-agnostic agent loop with `ClaudeProvider` (Anthropic API,
  `claude-opus-5`); Gemini planned as a drop-in provider.
- Typer CLI: `generate-sample`, `sync`, `status`, `ask`, `chat`; executed SQL
  shown in a panel with every answer.
- Unit tests for column mapping, row normalization, and deal identity.

### Fixed
- Deals appearing in both an Excel export and a PowerPoint table for the same
  snapshot date were double-counted. Added the deduplicated `deals_snapshots`
  view (xlsx wins over pptx) and pointed `deals_current` and the agent at it.

## [0.1.0] - 2026-07-24

### Added
- Initial repository: architecture design document (DESIGN.md), README, and a
  `.gitignore` that keeps company data (spreadsheets, decks, DuckDB files, API
  keys) out of the repo.

[0.3.1]: https://github.com/wasomma/sales-data-agent/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/wasomma/sales-data-agent/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/wasomma/sales-data-agent/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/wasomma/sales-data-agent/releases/tag/v0.1.0
