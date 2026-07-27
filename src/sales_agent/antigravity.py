"""Gemini-powered backend: drives headless Antigravity CLI (`agy -p`).

Same idea as claude_code.py — no API key, just the work-provisioned Antigravity
subscription — but the plumbing differs in three ways that are worth knowing
before you touch this file:

1. There is no `--mcp-config`. Antigravity reads MCP servers ONLY from the
   global `~/.gemini/config/mcp_config.json`, so registering the sales server is
   a one-time setup step (`sales setup-agy`), not something we can do per call.
2. There is no `--allowedTools`. Tool scoping lives in the CLI's own
   settings.json permissions. In headless mode the permission mode is
   `request-review`, which auto-denies anything not explicitly allowed — so the
   agent cannot reach its built-in shell/file/browser tools unless the user
   allowed them. `sales setup-agy` prints the rules to add.
3. MCP calls surface through a generic `call_mcp_tool`, not as
   `mcp__sales__run_sql`. The executed SQL is dug out of the event stream by
   _find_sql below rather than read from a known field.

`--output-format stream-json` is undocumented (it does not appear in `agy
--help`) but is supported and gives us the event stream we need.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

from .agent import SYSTEM_PROMPT, EventHandler

QUESTION_TIMEOUT_S = 600
DEFAULT_MODEL = "gemini-3.1-pro-high"

# Substring of the CLI's own error when a tool was auto-denied in headless mode.
_PERMISSION_HINT = 'required the "mcp" permission'


def find_agy() -> str | None:
    """Locate the agy executable, including the default install dir on Windows."""
    found = shutil.which("agy")
    if found:
        return found
    # A terminal opened before `agy install` ran has a stale PATH; look anyway.
    fallback = Path(os.environ.get("LOCALAPPDATA", "")) / "agy" / "bin" / "agy.exe"
    return str(fallback) if fallback.exists() else None


def _looks_like_sql(text: str) -> bool:
    head = text.lstrip().lower()
    return head.startswith("select") or head.startswith("with")


def _walk(obj):
    """Yield every dict nested anywhere inside a decoded JSON value."""
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _walk(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _walk(value)


def _find_sql(event: dict) -> list[str]:
    """Pull executed SQL out of an event without assuming its exact shape.

    The tool-call payload nests differently across agy versions, and the args
    may arrive either as a dict or as a JSON-encoded string, so we scan for any
    "query" that looks like SQL instead of hard-coding a path into the event.
    """
    found: list[str] = []
    for node in _walk(event):
        query = node.get("query")
        if isinstance(query, str) and _looks_like_sql(query):
            found.append(query)
        # Tool arguments are sometimes carried as a JSON string.
        for value in node.values():
            if isinstance(value, str) and '"query"' in value:
                try:
                    decoded = json.loads(value)
                except (json.JSONDecodeError, ValueError):
                    continue
                for inner in _walk(decoded):
                    inner_query = inner.get("query")
                    if isinstance(inner_query, str) and _looks_like_sql(inner_query):
                        found.append(inner_query)
    return found


class AntigravityBackend:
    """Same interface as the other backends: .ask(), .reset(), .on_event."""

    def __init__(self, console: Console | None = None, show_sql: bool = True,
                 model: str | None = None, on_event: EventHandler | None = None):
        self.exe = find_agy()
        if not self.exe:
            raise RuntimeError(
                "Antigravity CLI (agy) not found on PATH. Install it, run "
                "`agy install`, then open a new terminal. See `sales setup-agy`."
            )
        self.console = console or Console()
        self.show_sql = show_sql
        self.on_event = on_event
        self.model = model or os.getenv("SALES_AGENT_AGY_MODEL", DEFAULT_MODEL)
        self.conversation_id: str | None = None

    def _emit(self, event: dict) -> None:
        """Route a progress event to the caller's handler, or print it."""
        if self.on_event is not None:
            self.on_event(event)
        elif self.show_sql and event["type"] == "sql":
            self.console.print(Panel(
                Syntax(event["query"], "sql", word_wrap=True),
                title="SQL", border_style="dim", title_align="left"))

    def reset(self) -> None:
        """Start a fresh conversation, dropping prior context."""
        self.conversation_id = None

    def _prompt(self, question: str) -> str:
        """agy has no --append-system-prompt, so the rules ride with the first
        question; later turns resume the same conversation and still have them."""
        if self.conversation_id:
            return question
        return f"{SYSTEM_PROMPT}\n\nQuestion: {question}"

    def _command(self, question: str) -> list[str]:
        cmd = [self.exe, "-p", self._prompt(question),
               "--output-format", "stream-json",
               "--model", self.model]
        if self.conversation_id:
            cmd += ["--conversation", self.conversation_id]
        return cmd

    def _handle_event(self, event: dict, seen: set[str]) -> str | None:
        """Emit SQL panels as they happen; return the final text on result."""
        kind = event.get("event")
        if kind == "init":
            self.conversation_id = event.get("conversation_id") or self.conversation_id
            return None
        if kind == "result":
            result = event.get("result", {})
            self.conversation_id = result.get("conversation_id") or self.conversation_id
            if result.get("status") not in (None, "SUCCESS"):
                detail = result.get("error") or result.get("status")
                return f"Antigravity error: {detail}"
            return result.get("response", "")
        # Any other event may carry a tool call; step_update repeats as a step
        # streams, so dedupe on the query text itself.
        for query in _find_sql(event):
            if query not in seen:
                seen.add(query)
                self._emit({"type": "sql", "query": query})
        return None

    def ask(self, question: str) -> str:
        proc = subprocess.Popen(
            self._command(question),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
        )
        final: str | None = None
        seen_sql: set[str] = set()
        plain_lines: list[str] = []
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                plain_lines.append(line)
                continue
            result = self._handle_event(event, seen_sql)
            if result is not None:
                final = result
                break  # don't wait on MCP shutdown; reap below
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        if final is not None:
            return final

        stderr = proc.stderr.read().strip() if proc.stderr else ""
        if _PERMISSION_HINT in stderr:
            return ("Antigravity denied the sales tools. Headless mode cannot "
                    "prompt for permission, so the rules must be pre-approved.\n\n"
                    "Fix it with: **sales setup-agy**")
        detail = " | ".join(plain_lines[-3:]) or stderr[-500:]
        return f"Antigravity produced no result. {detail}".strip()
