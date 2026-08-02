# Deployment phases — VPS → work PC → work cloud

Three-phase path from "IT hasn't approved the cloud concept" to a properly
sanctioned deployment in the work cloud. Each phase is a working daily tool;
each successive phase moves the data and the runtime closer to work-controlled
infrastructure. Companion docs: [WORK.md](WORK.md) (work-machine runbook,
data-egress analysis, staged verification) and [README.md](README.md) (the
public replay demo, which stays synthetic forever).

**Risk statement, up front.** Phase 1 puts real CRM exports and the work
Gemini key on a personally controlled VPS. That is the riskiest configuration
in this document from a policy standpoint — riskier than the cloud concept IT
is hesitating on — and discovery without any sign-off would hurt the case for
Phases 2–3. The Phase 1 design below exists to shrink that exposure (minimum
data, minimum retention, isolation from the box's other services, a kill
switch), and the gate before real data goes up is the key owner's OK. Key
usage is visible in the Google console either way. Phase 1 should be
short-lived: decommission its real-data instance the day Phase 2 works.

---

## Phase 1 — personal VPS, real data, work Gemini key

**Goal:** the agent as a daily working tool, reachable from anywhere via a
password-protected web page, while the work-infrastructure phases are
unblocked.

### Architecture

A second, separate deployment on `guild-vps`, alongside — never replacing —
the public replay demo:

| | Replay demo (existing) | Live instance (new) |
|---|---|---|
| Path | `/opt/sales-demo` | `/opt/sales-live` |
| Port | 8140 (localhost) | 8141 (localhost) |
| Backend | `SALES_AGENT_BACKEND=replay` | `SALES_AGENT_PROVIDER=gemini` + work key |
| Data | `demo/recording.json` only | real DuckDB, treated as disposable cache |
| Service user | `www-data` | dedicated `salesagent` user |
| Caddy | `wasomma-sales.duckdns.org` | new subdomain, own `basic_auth` block |

Notes:

- **No GitHub Pages.** The chat UI is served by the FastAPI backend
  (`sales serve`); GitHub Pages is static-only and cannot password-protect
  anything. GitHub remains the code host. Caddy's `basic_auth` on the new
  subdomain *is* the username/password protection — no app code change.
- Follow the existing demo deploy pattern in [README.md](README.md): append a
  Caddy site block (never rewrite the Caddyfile), `caddy validate` before
  reload, systemd service with `Restart=on-failure`.
- **Isolation:** the box also runs guild-mp and fpv-sim. The live service runs
  as its own `salesagent` user; `data/` and `.env` (the work key) are
  `chmod 600`/`700` so no other service can read them.
- **Single user.** Phase 1 is one person. This defers the per-session
  conversation work (the current `web.py` holds one global conversation) and
  avoids multiplying real-data exposure on a personal box. The team joins in
  Phase 2/3.

### Getting data up

Run `sales sync` on the work PC against real exports, then `scp` the resulting
`data/sales.duckdb` to the VPS (or scp the raw exports and sync server-side).
Manual scp first; an authenticated upload page only if the friction warrants
it. Source of truth stays at work — the VPS copy is a cache.

### Gate before the first real row (extends WORK.md §2 sign-off)

- [ ] Key owner confirms the dataset may be sent to this Gemini tenant.
- [ ] Key owner confirms API calls **from non-work infrastructure** are
      acceptable.
- [ ] `excluded_columns` set in `mapping.yaml` (drop `owner` at minimum if rep
      names are sensitive).
- [ ] No `.pptx` decks ingested — slide narrative is usually more sensitive
      than the numbers.

Everything before this gate — deploy, Caddy, synthetic-data verification per
WORK.md Stage 0/1 — can proceed immediately.

### Containment rules

- No off-box backups of `data/`. The VPS copy is disposable by design.
- Kill switch (document it in the service's README on the box):
  `systemctl stop sales-live && rm -rf /opt/sales-live/data`
- The replay demo remains the only thing shown publicly or to IT/management.
  Never run `record-demo` on the live instance.

### Exit criteria

- Daily use, answers trusted (SQL read and spot-checked).
- The ~10-question eval set from WORK.md Stage 3 exists and passes.
- IT conversation for Phase 2 started, using the replay demo as the showpiece.

---

## Phase 2 — always-on work PC (the IT-defensible phase)

**Goal:** same tool, but data and runtime live on a work asset inside work IT
infrastructure. The only egress is the Gemini API on the company key. Frame it
to IT exactly that way — this phase dissolves most of Phase 1's risk, so get
here quickly.

### Architecture

- The app on an always-on office PC; `data/inbox` fed by manual exports or a
  shared-drive folder teammates drop files into, with a scheduled
  `sales sync`.
- Bind `sales serve` to the LAN IP with a Windows firewall rule; teammates
  reach `http://<office-pc>:8000`. **LAN-only** — no Cloudflare Tunnel,
  Tailscale, or any other hole punched out of the work network.
- Run as a Windows service or Task Scheduler at-boot task with
  restart-on-failure. Upgrades: `git pull` + WORK.md Stage 1 synthetic
  verification + the eval set.

### Code changes (the two real ones in this roadmap)

1. **Per-session conversations** in `web.py` — one global conversation cannot
   serve a team; give each browser session its own context with a TTL.
2. **In-app username/password auth** — no Caddy sits naturally on a Windows
   office PC, so add basic-auth middleware to FastAPI with hashed credentials
   in config. In-app auth also travels to any future host.

### On decommissioning Phase 1

The day Phase 2 works: stop the VPS live service, delete `/opt/sales-live`'s
data and key, revert the VPS to demo-only.

### Exit criteria

- Teammates using it over the LAN with individual sessions.
- Survives a reboot unattended.
- IT engaged on the Phase 3 cloud plan with a working, work-hosted precedent
  to point at.

---

## Phase 3 — work cloud

**Goal:** the sanctioned end state — no dependence on a PC under a desk.
This is the `sales-data-service` plan: a **private** work repo (this public
repo stays synthetic/demo), Cloud Run behind **IAP**, Sheets/Drive as the
ingestion source, Vertex AI as the model path.

- IAP gives Google Workspace SSO scoped to company accounts natively — the
  proper version of the login requirement, with no auth code to maintain.
- Engineering work: a Dockerfile (write it at the end of Phase 2),
  externalized state (rebuild DuckDB from Drive exports on boot, or persist to
  GCS), and reading the IAP identity header for per-user attribution.
- Known blockers: work GCP project provisioning, credential type
  (Vertex vs. Developer API — see WORK.md §4 key-type notes), Drive folder id.

---

## Engineering roadmap (build once, reuse forward)

| Item | Needed by | Effort |
|---|---|---|
| Second VPS service + Caddy block + `salesagent` user | Phase 1 | Hours (mirrors demo deploy) |
| `excluded_columns` decision + eval set | Phase 1 | An afternoon |
| Per-session conversations in `web.py` | Phase 2 | Small |
| In-app basic auth | Phase 2 | Small |
| Windows service wrapper | Phase 2 | Small |
| Dockerfile + externalized state + IAP identity | Phase 3 | The real Phase 3 work |

## Open questions

1. Gemini key owner's OK for calls from non-work infrastructure — the gate
   for Phase 1 real data.
2. Does the always-on Phase 2 PC exist, with admin rights (Python, firewall
   rule, service creation)?
3. Is LAN-only team access acceptable in Phase 2, or are teammates remote
   (which pushes team access to Phase 3)?
4. Subdomain for the Phase 1 live instance
   (e.g. `wasomma-sales-live.duckdns.org`).
