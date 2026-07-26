# Hosting the demo

This deploys the **replay** backend only — pre-recorded answers, no LLM call, no
API key, no Claude login on the server. Nothing here should ever be pointed at
real company data.

The target box already serves other sites from one Caddyfile. **Append** the
site block below; never rewrite that file.

## 1. Code and dependencies

```bash
sudo mkdir -p /opt/sales-demo && sudo chown $USER /opt/sales-demo
git clone https://github.com/wasomma/sales-data-agent.git /opt/sales-demo
cd /opt/sales-demo
python3 -m venv .venv
.venv/bin/pip install -e ".[web]"
```

No `sales sync`, no DuckDB, no data files: in replay mode the app reads
`demo/recording.json` and nothing else.

Verify before exposing it:

```bash
SALES_AGENT_BACKEND=replay .venv/bin/sales serve --port 8140 --no-open
curl -s localhost:8140/api/meta        # should report "demo": true
```

## 2. Service

`/etc/systemd/system/sales-demo.service`

```ini
[Unit]
Description=Sales Data Agent demo (replay backend)
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/sales-demo
Environment=SALES_AGENT_BACKEND=replay
ExecStart=/opt/sales-demo/.venv/bin/sales serve --port 8140 --no-open
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now sales-demo
sudo systemctl status sales-demo
```

The app binds `127.0.0.1` only — it is never reachable except through Caddy.

## 3. Caddy

Generate a password hash first, then **append** this block to the existing
Caddyfile. Do not touch the blocks already in it.

```bash
caddy hash-password --plaintext 'CHOOSE-A-PASSWORD'
```

```caddy
sales-demo.example.com {
    basic_auth {
        demo <PASTE-THE-HASH-HERE>
    }
    reverse_proxy 127.0.0.1:8140
}
```

```bash
sudo caddy validate --config /etc/caddy/Caddyfile   # check BEFORE reloading
sudo systemctl reload caddy
```

Caddy streams `text/event-stream` without buffering, so the live-SQL behaviour
works through the proxy unchanged.

## 4. Updating the demo

Re-record locally against the synthetic dataset, commit, then on the box:

```bash
cd /opt/sales-demo && git pull && sudo systemctl restart sales-demo
```

## Notes

- Basic auth is the point, not decoration. Without it the URL is an open
  endpoint for anyone who finds it.
- DNS: point the chosen subdomain at the box before reloading Caddy, or the
  certificate request fails.
- Pick a port nothing else on the box is using; 8140 is a suggestion, check first.
