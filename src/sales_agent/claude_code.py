"""Subscription-powered backend: drives headless Claude Code (`claude -p`).

No API key needed — uses the Claude subscription that Claude Code is logged in
with. The agent's tools are served to Claude Code via the MCP server in
mcp_server.py; Claude Code runs the tool loop itself. We stream its JSON events
so the executed SQL can still be shown to the user, and we resume the same
Claude Code session across questions so chat keeps its context.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

from .agent import SYSTEM_PROMPT

ALLOWED_TOOLS = "mcp__sales__get_schema,mcp__sales__run_sql,mcp__sales__list_sources"
QUESTION_TIMEOUT_S = 600


def find_claude() -> str | None:
    return shutil.which("claude")


class ClaudeCodeBackend:
    def __init__(self, console: Console | None = None, show_sql: bool = True,
                 model: str | None = None):
        self.exe = find_claude()
        if not self.exe:
            raise RuntimeError(
                "Claude Code CLI not found on PATH. Install it (or set "
                "ANTHROPIC_API_KEY to use the direct API backend instead)."
            )
        self.console = console or Console()
        self.show_sql = show_sql
        # None = let Claude Code use its configured default model
        self.model = model or os.getenv("SALES_AGENT_CLAUDE_CODE_MODEL")
        self.session_id: str | None = None

    def _mcp_config_file(self) -> str:
        """Write the MCP config to a temp file; some Claude Code versions only
        accept --mcp-config as a path, not inline JSON."""
        if getattr(self, "_mcp_config_path", None):
            return self._mcp_config_path
        config = {
            "mcpServers": {
                # sys.executable is this venv's python, so the package resolves.
                "sales": {"command": sys.executable, "args": ["-m", "sales_agent.mcp_server"]}
            }
        }
        fd, path = tempfile.mkstemp(prefix="sales_mcp_", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(config, f)
        self._mcp_config_path = path
        return path

    def _command(self, question: str) -> list[str]:
        cmd = [self.exe, "-p", question,
               "--output-format", "stream-json", "--verbose",
               "--mcp-config", self._mcp_config_file(), "--strict-mcp-config",
               "--allowedTools", ALLOWED_TOOLS,
               "--append-system-prompt", SYSTEM_PROMPT]
        if self.session_id:
            cmd += ["--resume", self.session_id]
        if self.model:
            cmd += ["--model", self.model]
        # .cmd shims can't be exec'd directly on Windows
        if cmd[0].lower().endswith((".cmd", ".bat")):
            cmd = ["cmd", "/c"] + cmd
        return cmd

    def _handle_event(self, event: dict) -> str | None:
        """Print SQL panels as they happen; return final text on the result event."""
        etype = event.get("type")
        if etype == "assistant":
            for block in event.get("message", {}).get("content", []):
                if (self.show_sql and block.get("type") == "tool_use"
                        and block["name"].endswith("run_sql")):
                    self.console.print(Panel(
                        Syntax(block["input"].get("query", ""), "sql", word_wrap=True),
                        title="SQL", border_style="dim", title_align="left"))
        elif etype == "result":
            self.session_id = event.get("session_id") or self.session_id
            if event.get("is_error"):
                return f"Claude Code error: {event.get('result') or event.get('subtype', 'unknown')}"
            return event.get("result", "")
        return None

    def ask(self, question: str) -> str:
        proc = subprocess.Popen(
            self._command(question),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
        )
        final: str | None = None
        plain_lines: list[str] = []
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                plain_lines.append(line)  # e.g. "Error: ..." startup failures
                continue
            result = self._handle_event(event)
            if result is not None:
                final = result
                break  # claude can hang on MCP shutdown; don't wait for exit
        # Reap the process; kill if it lingers (known MCP-shutdown hang).
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        if final is None:
            detail = " | ".join(plain_lines[-3:])
            if not detail and proc.stderr:
                detail = proc.stderr.read().strip()[-500:]
            return f"Claude Code produced no result. {detail}".strip()
        return final
