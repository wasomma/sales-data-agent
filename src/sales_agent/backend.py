"""Backend selection, shared by the CLI and the web UI.

Priority: SALES_AGENT_BACKEND env override ('api' | 'claude-code'), else the
direct API if ANTHROPIC_API_KEY is set, else headless Claude Code (works with a
Claude subscription — no API key needed).
"""

import os

from rich.console import Console

from .agent import EventHandler


def make_backend(console: Console | None = None, show_sql: bool = True,
                 on_event: EventHandler | None = None):
    """Return a backend exposing .ask(question) -> str and .reset()."""
    backend = os.getenv("SALES_AGENT_BACKEND")
    if backend == "api" or (backend is None and os.getenv("ANTHROPIC_API_KEY")):
        from .agent import SalesAgent
        return SalesAgent(console=console, show_sql=show_sql, on_event=on_event)
    from .claude_code import ClaudeCodeBackend
    return ClaudeCodeBackend(console=console, show_sql=show_sql, on_event=on_event)


def backend_name() -> str:
    """Human-readable label for the backend make_backend() would pick."""
    backend = os.getenv("SALES_AGENT_BACKEND")
    if backend == "api" or (backend is None and os.getenv("ANTHROPIC_API_KEY")):
        return "Anthropic API"
    return "Claude subscription"
