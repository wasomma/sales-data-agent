"""Provider-agnostic agent loop: question -> tool calls (SQL) -> grounded answer."""

from typing import Callable

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

from .llm import LLMProvider, get_provider
from .tools import TOOL_DEFINITIONS, execute_tool

# A progress event is a dict like {"type": "sql", "query": "SELECT ..."}. The CLI
# leaves on_event unset and gets rich panels; the web UI passes a callback so it
# can stream the same information to the browser instead.
EventHandler = Callable[[dict], None]

SYSTEM_PROMPT = """\
You are a sales-data analyst agent. You answer questions about the company's sales
pipeline using a DuckDB database of deal snapshots ingested from CRM exports.

Rules:
- Answer ONLY from query results. Never estimate, extrapolate, or use outside
  knowledge for numbers. If the data cannot answer the question, say so plainly.
- Call get_schema before your first query in a conversation so filters use real
  column values.
- Use the deals_current view for "as of now" questions; use the deals_snapshots
  view with as_of_date for point-in-time or change-over-time questions. Do not
  query the raw deals table (it can contain cross-file duplicates).
- Closed deals are NOT open business. Any question about pipeline, open deals,
  forecast, "top deals", deals closing in some period, or a rollup by rep or
  account must filter them out in SQL with
  stage NOT IN ('Closed Won', 'Closed Lost'),
  and the answer must say they were excluded. A closed deal appearing in such a
  list is a wrong answer, not a rounding difference.
  The exception is a descriptive breakdown across every stage (average deal size
  by stage, deal counts by stage, win rates) — there, keep the closed stages and
  label them. If the question is ambiguous, exclude them and say so.
- Report the deal count alongside any total or average, and give the as_of date
  of the snapshot you used.
- Currency values are USD; format large numbers readably (e.g. $1.2M, $450K).
- Keep answers concise: lead with the direct answer, then a compact table or list
  when it helps.
- Close with one or two sentences on anything in the results that a sales leader
  would want flagged — close dates already in the past, deals moved by identical
  amounts, a single rep or account dominating. Say nothing if nothing stands out;
  never invent a pattern the query results do not show.
- If a query errors, fix the SQL and retry rather than giving up.
"""

MAX_TURNS = 12  # safety cap on the tool loop


class SalesAgent:
    def __init__(self, provider: LLMProvider | None = None, console: Console | None = None,
                 show_sql: bool = True, on_event: EventHandler | None = None):
        self.provider = provider or get_provider()
        self.console = console or Console()
        self.show_sql = show_sql
        self.on_event = on_event
        self.messages: list[dict] = []

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
        self.messages = []

    def ask(self, question: str) -> str:
        self.messages.append({"role": "user", "content": question})
        for _ in range(MAX_TURNS):
            turn = self.provider.send(SYSTEM_PROMPT, self.messages, TOOL_DEFINITIONS)
            self.messages.append(self.provider.assistant_message(turn))
            if not turn.tool_calls:
                return turn.text
            results = []
            for call in turn.tool_calls:
                if call.name == "run_sql":
                    self._emit({"type": "sql", "query": call.input.get("query", "")})
                else:
                    self._emit({"type": "tool", "name": call.name})
                results.append((call.id, execute_tool(call.name, call.input)))
            self.messages.append(self.provider.tool_results_message(results))
        return "Stopped: exceeded the maximum number of tool-use turns for one question."
