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


def _provider() -> str:
    return (os.getenv("SALES_AGENT_PROVIDER") or "").lower()


def _wants_api() -> bool:
    """Whether the direct-API backend should handle this run.

    Either asked for explicitly, or implied by having a key for the selected
    provider: SALES_AGENT_PROVIDER=gemini with GEMINI_API_KEY set is enough on
    its own, so the Gemini API path does not also need SALES_AGENT_BACKEND=api.
    """
    backend = os.getenv("SALES_AGENT_BACKEND")
    if backend == "api":
        return True
    if backend is not None:
        return False
    if _provider() == "gemini":
        return bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
    return bool(os.getenv("ANTHROPIC_API_KEY"))


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
    if _wants_api():
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
    if _wants_api():
        return "Gemini API" if _provider() == "gemini" else "Anthropic API"
    return "Claude subscription"
