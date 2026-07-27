"""One-time wiring so headless `agy` can reach the sales MCP server.

Antigravity has no per-invocation MCP flag, so the server must be registered in
the user's global config and its tools pre-approved in the CLI's settings. Both
files are shared with every other use of agy on this machine, so everything here
merges into what is already present and never rewrites a file wholesale.

Encoding matters more than it should: agy's config parser is Go's encoding/json,
which rejects a UTF-8 BOM outright. A BOM makes the CLI behave as though no MCP
servers exist at all, and the only evidence is a line in
~/.gemini/antigravity-cli/log/cli-*.log. Everything here writes BOM-free and
doctor() checks for it explicitly.
"""

import json
import shutil
import sys
from pathlib import Path

SERVER_NAME = "sales"

GEMINI_HOME = Path.home() / ".gemini"
MCP_CONFIG_PATH = GEMINI_HOME / "config" / "mcp_config.json"
SETTINGS_PATH = GEMINI_HOME / "antigravity-cli" / "settings.json"

# The sales tools are read-only SQL, so a single scoped allow is all the agent
# needs. Everything else stays denied: headless mode runs with permission_mode
# request-review, which auto-denies whatever is not explicitly allowed, and the
# command(*) deny makes the shell block explicit rather than incidental.
ALLOW_RULE = f"mcp({SERVER_NAME}/*)"
DENY_RULES = ["command(*)"]


def server_entry() -> dict:
    """stdio MCP server definition. sys.executable is this venv's interpreter,
    so `-m sales_agent.mcp_server` resolves without activating anything."""
    return {"command": sys.executable, "args": ["-m", "sales_agent.mcp_server"]}


def read_json(path: Path) -> dict:
    """Load a config file, tolerating absent, empty, and BOM-prefixed files."""
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8-sig").strip()
    if not raw:
        return {}
    return json.loads(raw)


def write_json(path: Path, data: dict) -> None:
    """Write UTF-8 with no BOM and a trailing newline (Go's json parser is picky)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")


def _backup(path: Path) -> Path | None:
    if not path.exists() or not path.read_text(encoding="utf-8-sig").strip():
        return None
    backup = path.with_suffix(path.suffix + ".bak-sales")
    shutil.copy2(path, backup)
    return backup


def install_server() -> tuple[bool, Path | None]:
    """Register the sales MCP server, preserving any other servers.

    Returns (changed, backup_path).
    """
    config = read_json(MCP_CONFIG_PATH)
    servers = config.setdefault("mcpServers", {})
    entry = server_entry()
    if servers.get(SERVER_NAME) == entry:
        return False, None
    backup = _backup(MCP_CONFIG_PATH)
    servers[SERVER_NAME] = entry
    write_json(MCP_CONFIG_PATH, config)
    return True, backup


def permissions_block() -> str:
    """The settings.json fragment the user needs, for printing."""
    return json.dumps({"permissions": {"allow": [ALLOW_RULE], "deny": DENY_RULES}}, indent=2)


def missing_permissions() -> list[str]:
    """Which of our rules are absent from settings.json."""
    try:
        settings = read_json(SETTINGS_PATH)
    except json.JSONDecodeError:
        return [ALLOW_RULE, *DENY_RULES]
    permissions = settings.get("permissions") or {}
    allow = permissions.get("allow") or []
    deny = permissions.get("deny") or []
    missing = []
    if ALLOW_RULE not in allow and "mcp(*)" not in allow:
        missing.append(ALLOW_RULE)
    missing += [rule for rule in DENY_RULES if rule not in deny]
    return missing


def apply_permissions() -> tuple[list[str], Path | None]:
    """Add our rules to settings.json, keeping every existing entry.

    Opt-in only: this widens what agy may do without prompting, on tooling the
    user may not own, so the CLI never calls it unless asked.
    Returns (rules_added, backup_path).
    """
    missing = missing_permissions()
    if not missing:
        return [], None
    backup = _backup(SETTINGS_PATH)
    settings = read_json(SETTINGS_PATH)
    permissions = settings.setdefault("permissions", {})
    allow = permissions.setdefault("allow", [])
    deny = permissions.setdefault("deny", [])
    if ALLOW_RULE in missing:
        allow.append(ALLOW_RULE)
    for rule in DENY_RULES:
        if rule in missing:
            deny.append(rule)
    write_json(SETTINGS_PATH, settings)
    return missing, backup


def doctor() -> list[tuple[bool, str]]:
    """Diagnostics for the whole chain, most fundamental first."""
    from .antigravity import find_agy

    checks: list[tuple[bool, str]] = []

    exe = find_agy()
    checks.append((bool(exe), f"agy executable: {exe or 'NOT FOUND — run agy install, then reopen your terminal'}"))

    if MCP_CONFIG_PATH.exists():
        head = MCP_CONFIG_PATH.read_bytes()[:3]
        if head == b"\xef\xbb\xbf":
            checks.append((False, f"{MCP_CONFIG_PATH} starts with a UTF-8 BOM — agy will "
                                  "silently load no MCP servers. Re-run `sales setup-agy`."))
        else:
            checks.append((True, "mcp_config.json encoding is BOM-free"))
    else:
        checks.append((False, f"{MCP_CONFIG_PATH} does not exist — run `sales setup-agy`"))

    try:
        servers = (read_json(MCP_CONFIG_PATH).get("mcpServers") or {})
        registered = servers.get(SERVER_NAME)
        if registered == server_entry():
            checks.append((True, f"MCP server '{SERVER_NAME}' registered for {sys.executable}"))
        elif registered:
            checks.append((False, f"MCP server '{SERVER_NAME}' points at a different interpreter "
                                  f"({registered.get('command')}) — re-run `sales setup-agy`"))
        else:
            checks.append((False, f"MCP server '{SERVER_NAME}' not registered — run `sales setup-agy`"))
    except json.JSONDecodeError as exc:
        checks.append((False, f"mcp_config.json is not valid JSON: {exc}"))

    missing = missing_permissions()
    if missing:
        checks.append((False, "settings.json is missing: " + ", ".join(missing)))
    else:
        checks.append((True, "settings.json permissions allow the sales tools"))

    return checks
