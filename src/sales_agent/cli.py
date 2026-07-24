"""Typer CLI: generate-sample, sync, status, ask, chat."""

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

app = typer.Typer(help="Ask natural-language questions about your sales data.",
                  no_args_is_help=True)
console = Console()


def _make_agent(show_sql: bool):
    """Pick the LLM backend.

    Priority: SALES_AGENT_BACKEND env override ('api' | 'claude-code'), else the
    direct API if ANTHROPIC_API_KEY is set, else headless Claude Code (works
    with a Claude subscription — no API key needed).
    """
    import os

    backend = os.getenv("SALES_AGENT_BACKEND")
    if backend == "api" or (backend is None and os.getenv("ANTHROPIC_API_KEY")):
        from .agent import SalesAgent
        return SalesAgent(console=console, show_sql=show_sql)
    from .claude_code import ClaudeCodeBackend
    return ClaudeCodeBackend(console=console, show_sql=show_sql)


@app.command("generate-sample")
def generate_sample():
    """Write a deterministic synthetic dataset into data/inbox."""
    from .generate import generate
    for name in generate():
        console.print(f"[green]created[/green] data/inbox/{name}")
    console.print("Now run: [bold]sales sync[/bold]")


@app.command()
def sync():
    """Ingest new/changed files from data/inbox into DuckDB."""
    from .ingest import sync as run_sync
    results = run_sync()
    if not results:
        console.print("Inbox is empty — drop .xlsx/.pptx files into data/inbox "
                      "or run [bold]sales generate-sample[/bold].")
        raise typer.Exit(0)
    table = Table("file", "status", "rows", "rejected")
    for r in results:
        table.add_row(r["file"], r["status"], str(r["rows"]), str(r["rejected"]))
    console.print(table)


@app.command()
def status():
    """Show ingested sources and row counts."""
    from .tools import list_sources
    console.print(list_sources())


@app.command()
def ask(question: str = typer.Argument(..., help="A question about your sales data."),
        no_sql: bool = typer.Option(False, "--no-sql", help="Hide the executed SQL.")):
    """One-shot question, e.g.: sales ask "top 10 largest deals for 2026" """
    agent = _make_agent(show_sql=not no_sql)
    with console.status("thinking..."):
        answer = agent.ask(question)
    console.print(Markdown(answer))


@app.command()
def chat(no_sql: bool = typer.Option(False, "--no-sql", help="Hide the executed SQL.")):
    """Interactive chat session (Ctrl+C or 'exit' to quit)."""
    agent = _make_agent(show_sql=not no_sql)
    console.print("[bold]sales-data-agent[/bold] — ask about your pipeline. 'exit' to quit.\n")
    while True:
        try:
            question = console.input("[bold cyan]you>[/bold cyan] ").strip()
        except (KeyboardInterrupt, EOFError):
            break
        if not question:
            continue
        if question.lower() in ("exit", "quit"):
            break
        with console.status("thinking..."):
            answer = agent.ask(question)
        console.print(Markdown(answer))
        console.print()


if __name__ == "__main__":
    app()
