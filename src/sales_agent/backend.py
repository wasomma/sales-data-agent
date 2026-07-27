"""Backend selection, shared by the CLI and the web UI.

Priority: SALES_AGENT_BACKEND env override ('replay' | 'api' | 'agy' |
'claude-code'), else the direct API if ANTHROPIC_API_KEY is set, else headless
Claude Code (works with a Claude subscription — no API key needed).

'agy' is the Gemini path: headless Antigravity CLI on a work-provisioned
subscription. It is opt-in rather than auto-selected — having agy on PATH says
nothing about whether sending this data through that tenant is sanctioned.
"""

import os

from rich.console import Console

from .agent import EventHandler


def make_backend(console: Console | None = None, show_sql: bool = True,
                 on_event: EventHandler | None = None):
    """Return a backend exposing .ask(question) -> str and .reset()."""
    backend = os.getenv("SALES_AGENT_BACKEND")
    if backend == "replay":
        from .replay import ReplayBackend
        return ReplayBackend(console=console, show_sql=show_sql, on_event=on_event)
    if backend == "agy":
        from .antigravity import AntigravityBackend
        return AntigravityBackend(console=console, show_sql=show_sql, on_event=on_event)
    if backend == "api" or (backend is None and os.getenv("ANTHROPIC_API_KEY")):
        from .agent import SalesAgent
        return SalesAgent(console=console, show_sql=show_sql, on_event=on_event)
    from .claude_code import ClaudeCodeBackend
    return ClaudeCodeBackend(console=console, show_sql=show_sql, on_event=on_event)


# Live backends report failure as a normal answer string rather than raising, so
# callers that must not record a failure (record-demo) check these prefixes.
ERROR_PREFIXES = (
    "claude code error", "claude code produced",
    "antigravity error", "antigravity produced", "antigravity denied",
)


def is_error_answer(answer: str) -> bool:
    return not answer or answer.lower().startswith(ERROR_PREFIXES)


def is_replay() -> bool:
    return os.getenv("SALES_AGENT_BACKEND") == "replay"


def backend_name() -> str:
    """Human-readable label for the backend make_backend() would pick."""
    backend = os.getenv("SALES_AGENT_BACKEND")
    if backend == "replay":
        return "Demo — recorded answers"
    if backend == "agy":
        return "Gemini (Antigravity)"
    if backend == "api" or (backend is None and os.getenv("ANTHROPIC_API_KEY")):
        return "Anthropic API"
    return "Claude subscription"
