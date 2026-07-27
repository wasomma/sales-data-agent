"""Typer CLI: generate-sample, sync, status, ask, chat."""

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

app = typer.Typer(help="Ask natural-language questions about your sales data.",
                  no_args_is_help=True)
console = Console()


def _make_agent(show_sql: bool):
    """Pick the LLM backend (see backend.make_backend for the priority rules)."""
    from .backend import make_backend
    return make_backend(console=console, show_sql=show_sql)


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


DEMO_QUESTIONS = [
    "What are my top 10 largest deals closing in 2026?",
    "Total pipeline by stage",
    "Which deals slipped since the last snapshot?",
    "Who are my top 5 reps by open pipeline?",
    "What is the average deal size by stage?",
    "How much is forecast to close this quarter?",
]


@app.command("record-demo")
def record_demo(
    out: str = typer.Option("demo/recording.json", help="Where to write the recording."),
):
    """Run the demo questions through the real agent and save the answers.

    The result is what `SALES_AGENT_BACKEND=replay` serves, so the public demo
    shows genuine SQL and genuine prose without ever calling an LLM.
    """
    import json
    from datetime import date
    from pathlib import Path

    from .config import PROJECT_ROOT
    from .tools import list_sources

    agent = _make_agent(show_sql=False)
    exchanges = []
    for i, question in enumerate(DEMO_QUESTIONS, 1):
        console.print(f"[dim]({i}/{len(DEMO_QUESTIONS)})[/dim] {question}")
        events: list[dict] = []
        agent.on_event = events.append
        try:
            answer = agent.ask(question)
        finally:
            agent.on_event = None
        from .backend import is_error_answer
        if is_error_answer(answer):
            console.print(f"  [red]failed:[/red] {answer}")
            raise typer.Exit(1)
        sql_count = sum(1 for e in events if e["type"] == "sql")
        console.print(f"  [green]ok[/green] — {sql_count} quer(y/ies), {len(answer)} chars")
        exchanges.append({"question": question, "events": events, "answer": answer})
        agent.reset()  # each demo answer should stand alone, no carried context

    path = Path(out)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "recorded": date.today().isoformat(),
        "dataset": list_sources(),
        "exchanges": exchanges,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    console.print(f"\n[green]Wrote[/green] {path} ({len(exchanges)} exchanges)")
    console.print("Serve it with: [bold]set SALES_AGENT_BACKEND=replay && sales serve[/bold]")


@app.command("setup-agy")
def setup_agy(
    write_permissions: bool = typer.Option(
        False, "--write-permissions",
        help="Also add the permission rules to agy's settings.json."),
    check_only: bool = typer.Option(False, "--check", help="Diagnose only, change nothing."),
):
    """Wire the sales tools into the Antigravity CLI (the Gemini backend).

    Registers the MCP server in agy's global config. The permission rules are
    printed rather than applied unless --write-permissions is passed, because
    they widen what agy may do unprompted on possibly work-owned tooling.
    """
    from . import agy_setup

    if not check_only:
        changed, backup = agy_setup.install_server()
        if changed:
            console.print(f"[green]registered[/green] MCP server "
                          f"'{agy_setup.SERVER_NAME}' in {agy_setup.MCP_CONFIG_PATH}")
            if backup:
                console.print(f"[dim]previous config backed up to {backup}[/dim]")
        else:
            console.print("MCP server already registered — no change.")

        missing = agy_setup.missing_permissions()
        if missing and write_permissions:
            added, backup = agy_setup.apply_permissions()
            console.print(f"[green]added[/green] permission rules: {', '.join(added)}")
            if backup:
                console.print(f"[dim]previous settings backed up to {backup}[/dim]")
        elif missing:
            console.print(f"\n[yellow]Permission rules still needed[/yellow] in "
                          f"{agy_setup.SETTINGS_PATH}:")
            console.print(agy_setup.permissions_block())
            console.print("\nApply them with: [bold]sales setup-agy --write-permissions[/bold]")

    console.print("\n[bold]Checks[/bold]")
    checks = agy_setup.doctor()
    for ok, message in checks:
        console.print(f"  [{'green' if ok else 'red'}]{'ok  ' if ok else 'FAIL'}[/] {message}")
    if all(ok for ok, _ in checks):
        console.print("\nReady. Try: [bold]set SALES_AGENT_BACKEND=agy && sales ask "
                      '"total pipeline by stage"[/bold]')
    else:
        raise typer.Exit(1)


@app.command()
def serve(port: int = typer.Option(8000, help="Port to listen on."),
          host: str = typer.Option("127.0.0.1", help="Bind address; localhost by default."),
          open_browser: bool = typer.Option(True, "--open/--no-open",
                                            help="Open the chat UI in your browser.")):
    """Start the browser chat UI (Ctrl+C to stop)."""
    try:
        from .web import serve as run_server
    except ImportError:
        console.print("[red]The web UI needs extra packages.[/red] Install them with:\n"
                      '  [bold]pip install -e ".[web]"[/bold]')
        raise typer.Exit(1)

    url = f"http://{'localhost' if host == '127.0.0.1' else host}:{port}"
    # ASCII only: on Windows a piped stdout defaults to cp1252 and chokes on
    # characters like the arrow glyph.
    console.print(f"Sales Data Agent UI at [bold cyan]{url}[/bold cyan]   (Ctrl+C to stop)")
    if open_browser:
        import threading
        import webbrowser
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    run_server(host=host, port=port)


if __name__ == "__main__":
    app()
