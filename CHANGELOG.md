# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/). Each release is a git tag (`v0.x.y`)
pointing at the push that shipped it.

## [Unreleased]

### Added
- **`GeminiProvider`** — Gemini through the google-genai SDK with native function
  calling, selected by `SALES_AGENT_PROVIDER=gemini`. This is the path llm.py was
  designed around: the existing agent loop, tools and CLI are unchanged, and the
  tool schemas are handed to Gemini verbatim via `parameters_json_schema` rather
  than restated in a second dialect that could drift.
- `.env.example` now documents every backend and provider switch in one place.
- New `gemini` extra: `pip install -e ".[gemini]"`.

### Notes
- Two Gemini paths now exist and are not interchangeable: `SALES_AGENT_BACKEND=agy`
  (work subscription, via the Antigravity CLI, no key) and
  `SALES_AGENT_PROVIDER=gemini` (API key, direct). They take separate model
  settings, since Antigravity model ids are not API model ids.
- Anthropic pairs a tool result to its call by id; Gemini pairs by function name.
  The provider keeps an id-to-name map so the shared agent loop stays unaware.
- **The live API path is not yet verified** — no key was present when this landed.
  The translation logic is unit-tested against fakes; the network call is not.

## [0.6.1] - 2026-07-27

### Fixed
- **A malformed `run_sql` call no longer kills the question.** Gemini occasionally
  emits `run_sql` with empty arguments; pydantic rejected the call before reaching
  the tool body, and Antigravity treats a failed tool *call* as fatal — so one bad
  call ended the whole run. `query` now has a default and an omitted query comes
  back as correctable text, which the model can retry from. The advertised schema
  still marks `query` as required. Found when the first Gemini run of the six demo
  questions died on question 1; all six pass after the fix.

## [0.6.0] - 2026-07-27

### Added
- **Gemini backend** (`SALES_AGENT_BACKEND=agy`) driving the headless Antigravity
  CLI, so the agent can run on a work-provisioned Gemini subscription with no API
  key — the same trick as the Claude Code backend, different plumbing. Opt-in
  only: having `agy` on PATH never auto-selects it, because installation says
  nothing about whether the data may go through that tenant.
- `sales setup-agy` registers the MCP server in agy's global config and reports
  what is still missing. Antigravity has no `--mcp-config`, so registration is a
  one-time machine-level step rather than a per-invocation temp file.

### Notes
- Three Antigravity differences worth remembering: MCP servers load **only** from
  `~/.gemini/config/mcp_config.json` (a repo-local `.agents/mcp_config.json` is
  ignored); the config must be UTF-8 **without a BOM** or agy silently loads no
  servers at all; and there is no `--allowedTools`, so tool scoping lives in
  `permissions.allow` as `mcp(sales/*)`.
- `--output-format stream-json` is undocumented but supported, and is what makes
  the SQL panels work.
- Verified against the synthetic dataset: stage totals match the Claude-recorded
  answers exactly ($6.11M Prospecting / 25 deals, $19.7M open pipeline), and
  follow-up questions resolve referents from earlier turns via `--conversation`.
  Expect a slow first question (~90s, MCP cold start) and ~8s thereafter.

## [0.5.0] - 2026-07-26

### Added
- **Replay backend for public demos** (`SALES_AGENT_BACKEND=replay`). Serves
  pre-recorded exchanges from `demo/recording.json` and never calls an LLM, so a
  hosted demo costs nothing, consumes no subscription quota, and cannot be run up
  by whoever finds the URL. Unrecognized questions get an honest "this is a demo,
  here is what I can answer" reply instead of a wrong guess.
- `sales record-demo` captures those recordings by running the demo questions
  through the *real* agent once, so the SQL and prose on the demo are genuine.
  Each question is recorded with a fresh conversation so answers stand alone.
- The UI reads its suggested questions from the server, so in demo mode the
  chips are exactly what can be answered, above a banner stating it is replaying.

## [0.4.0] - 2026-07-26

### Added
- **Browser chat UI** — `sales serve` starts a local FastAPI app (`web.py`) and
  opens a single-page chat front-end (`static/index.html`, no build step and no
  external assets). Questions are POSTed and the response streams back as
  Server-Sent Events, so each SQL query appears in the transcript the moment the
  agent runs it. Binds to `127.0.0.1` only; needs the new `web` extra
  (`pip install -e ".[web]"`).
- `backend.py`: backend selection extracted from the CLI so the web UI and the
  terminal pick the same provider by the same rules.
- Both backends accept an `on_event` callback and expose `reset()`, so callers
  other than the terminal can consume progress events (SQL, tool use) and start
  a fresh conversation.

### Fixed
- `sales serve` printed a Unicode arrow that crashed on Windows when stdout was
  a pipe (cp1252 `UnicodeEncodeError`); console output is ASCII now.

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
