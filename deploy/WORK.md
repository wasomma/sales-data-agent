# Running at work — real data, work Gemini key

This is the runbook for the work environment: the agent installed on the work
machine, ingesting real CRM exports, with the **work Google API key** as the
LLM (`SALES_AGENT_PROVIDER=gemini`). It is the counterpart to `deploy/README.md`,
which hosts the public replay demo and must never touch real data.

The code path involved was verified live in v0.7.0 (all six demo questions
against the Gemini Developer API, cross-checked against the Claude recording),
so work setup is configuration and verification, not new code.

## 1. Where everything runs

Everything is local to the work machine except the model call:

```
work machine                                        Google
┌──────────────────────────────────────────┐
│ data/inbox/*.xlsx|pptx  (real exports)   │
│        │ sales sync                      │
│        ▼                                 │
│ data/sales.duckdb  (local file)          │      ┌─────────────┐
│        │ read-only SELECT                │      │ Gemini API  │
│        ▼                                 │ ───► │ (work key)  │
│ sales chat / ask / serve (localhost)     │ ◄─── └─────────────┘
└──────────────────────────────────────────┘
```

Rules that keep the two environments separate:

- Real exports, the DuckDB file, and the work key exist **only on the work
  machine**. Nothing syncs back to the personal machine or the public demo box.
- `data/` and `.env` are git-ignored, so `git pull` for upgrades is safe and
  `git push` from the work checkout can never carry data. Treat the work
  checkout as pull-only anyway — the GitHub repo is public.
- **Never run `sales record-demo` against real data.** It writes real answers
  into `demo/recording.json`, which is committed and served publicly.

## 2. What leaves the machine (read before first real question)

Per question, the Gemini API receives:

1. The question text and the system prompt.
2. `get_schema` output: table/column names, the distinct values of `stage`,
   `owner` (i.e. **rep names**), and `forecast_category`, and snapshot dates.
3. Each SQL query the model writes, and its **results** (capped at 200 rows per
   query) — deal names, accounts, amounts.
4. If decks are ingested: `slide_text` stores raw slide narrative, and the
   model *can* SELECT from it. If deck commentary is more sensitive than the
   numbers, don't drop `.pptx` files in the inbox.

Controls available before the first real ingest:

- `excluded_columns` in `mapping.yaml` drops canonical columns at ingest so
  they never enter the database at all (e.g. `excluded_columns: [owner]`).
  Required columns (`deal_name`, `account`, `amount`) cannot be excluded;
  misconfiguration fails loudly at `sales sync`.
- Ingestion is allowlist-based: columns not mapped in `mapping.yaml` (contact
  emails, phone numbers, notes) are never stored, so they can never be sent.

Sign-off checklist before Stage 2 below:

- [ ] The key's owner confirms this dataset may be sent to this Gemini tenant.
- [ ] Confirm the key is on a paid/business tier and what Google's data-use
      terms are for it (training/retention) — don't assume; ask whoever issued it.
- [ ] Decide `excluded_columns` and whether decks are in or out.

## 3. Install (work machine)

```bash
git clone https://github.com/wasomma/sales-data-agent.git
cd sales-data-agent
python -m venv .venv
.venv/Scripts/pip install -e ".[gemini]"        # add ",web" for the browser UI
```

Corporate-network notes: if pip fails on SSL, the proxy is likely re-signing
TLS — point pip at the corporate CA bundle (`pip config set global.cert
<path>`) rather than disabling verification. The Gemini SDK honors
`HTTPS_PROXY` if outbound calls need the proxy.

## 4. Configure

Copy `.env.example` to `.env` and set:

```ini
SALES_AGENT_PROVIDER=gemini
GEMINI_API_KEY=<work key>
# SALES_AGENT_GEMINI_MODEL=gemini-3.1-pro-preview   # the default; pinned on purpose
```

That is sufficient — with `SALES_AGENT_PROVIDER=gemini` and a key set, the
direct-API backend is selected automatically (`backend.py`).

Key-type wrinkles:

- An **AI Studio / Gemini Developer API** key works as-is.
- If the key turns out to be a **Vertex AI** key (issued from a GCP project),
  set `GOOGLE_GENAI_USE_VERTEXAI=true` as well — the google-genai SDK routes
  the same client through Vertex. Model ids may differ; start with
  `gemini-pro-latest`.
- If the pinned preview model 404s (previews get retired),
  `SALES_AGENT_GEMINI_MODEL=gemini-pro-latest` is the stable-alias fallback.

## 5. Staged verification

Do these in order; each stage isolates one new variable.

### Stage 0 — install proof (no key, no data)

```bash
.venv/Scripts/python -m pytest -q          # expect all green
.venv/Scripts/sales generate-sample
.venv/Scripts/sales sync                   # 3 files ingested, 0 rejected
.venv/Scripts/sales status
```

### Stage 1 — live key, synthetic data only

Still zero company data — this proves key, network, and the Gemini tool loop:

```bash
.venv/Scripts/sales ask "Total pipeline by stage"
```

Known-good figures for the synthetic dataset: **$6.11M Prospecting / 25
deals**, **$19.7M total open pipeline**. For a fuller pass, ask the six
questions in `cli.py:DEMO_QUESTIONS` and compare against
`demo/recording.json` — five of six should match on every figure (Q6 differs
in framing only; see the v0.7.0 changelog note).

If this stage fails: 404 → model id (see §4); 401/403 → key or tenant
restrictions; timeouts → proxy (§3).

### Stage 2 — first real export

1. Complete the §2 sign-off checklist; set `excluded_columns` **now**.
2. Reset the database so synthetic and real data never mix: delete
   `data/sales.duckdb` and clear `data/inbox/`.
3. Drop **one** real export into `data/inbox/` and run `sales sync`.
   - Unrecognized headers → extend the alias lists in `mapping.yaml` (matching
     is case-insensitive). A sheet needs `deal_name`, `account`, and `amount`
     mapped to count as deal data.
   - Check the rejected count and, if nonzero,
     `SELECT reason, count(*) FROM rejects GROUP BY 1` via `sales ask` or a
     DuckDB client — rejects are quarantined, never silently dropped.
   - `sales status`: confirm the inferred `as_of` date is right. It comes from
     a `YYYY-MM-DD` in the filename, else file mtime — rename the file if the
     mtime lies (e.g. re-downloaded exports).
4. Ask 3–5 questions you can verify by hand in the same spreadsheet
   (top-N by amount, count by stage, sum for one account). The SQL is printed
   with every answer — read it.

### Stage 3 — accuracy eval, then daily use

Write down ~10 question → hand-checked answer pairs from the real data and run
them after any model change, prompt change, or `git pull`. This is the eval
set DESIGN.md §9 calls for; it is what makes a model swap safe later.

## 6. Ongoing use

- New export → drop in `data/inbox/` → `sales sync`. Re-syncing unchanged
  files is a no-op (content hash); snapshots accumulate, so "what slipped
  since last month?" works once two real snapshots exist.
- Company policy on data location: set `SALES_AGENT_DATA_DIR` to move the
  database and inbox to an approved drive.
- Upgrades: `git pull` + rerun Stage 1 (synthetic figures) before trusting new
  code with real questions. `pytest -q` is the cheap regression check.
- `sales serve` binds `127.0.0.1` only — fine on the work machine; do not
  re-bind it to expose the UI beyond the machine without a real auth story.
