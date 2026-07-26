"""Local web UI: a browser chat front-end over the same agent the CLI uses.

Runs on localhost only by default. Questions are POSTed (never in a URL) and the
answer is streamed back as Server-Sent Events so the SQL appears in the browser
the moment the agent runs it, exactly like the terminal panels.
"""

import asyncio
import json
import queue
import threading
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from .backend import backend_name, make_backend
from .tools import list_sources

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Sales Data Agent")

# One conversation, one agent. The backends hold conversation state (message
# history or a Claude Code session id) and are not thread-safe, so a single lock
# serializes questions — correct for the single-user local tool this is.
_lock = threading.Lock()
_backend = None


def _get_backend():
    global _backend
    if _backend is None:
        _backend = make_backend(show_sql=True)
    return _backend


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/meta")
def meta() -> JSONResponse:
    """Backend label and ingested sources, for the header and the empty state."""
    try:
        sources_text = list_sources()
    except Exception as e:
        return JSONResponse({"backend": backend_name(), "sources": [],
                             "error": f"Could not read the database: {e}"})
    sources = []
    for line in sources_text.splitlines():
        if "|" not in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        fields = dict(p.split("=", 1) for p in parts[1:] if "=" in p)
        sources.append({
            "file": parts[0],
            "as_of": fields.get("as_of", ""),
            "rows": fields.get("rows", ""),
        })
    return JSONResponse({"backend": backend_name(), "sources": sources,
                         "error": None if sources else sources_text})


@app.post("/api/reset")
def reset() -> JSONResponse:
    with _lock:
        if _backend is not None:
            _backend.reset()
    return JSONResponse({"ok": True})


@app.post("/api/ask")
async def ask(request: Request) -> StreamingResponse:
    body = await request.json()
    question = (body.get("question") or "").strip()

    events: queue.Queue = queue.Queue()

    def run() -> None:
        try:
            if not question:
                events.put({"type": "error", "message": "Ask a question first."})
                return
            with _lock:
                backend = _get_backend()
                backend.on_event = events.put
                try:
                    answer = backend.ask(question)
                finally:
                    backend.on_event = None
            events.put({"type": "answer", "text": answer})
        except Exception as e:  # surfaced in the chat rather than a blank page
            events.put({"type": "error", "message": str(e)})
        finally:
            events.put(None)

    threading.Thread(target=run, daemon=True).start()

    async def stream():
        while True:
            event = await asyncio.to_thread(events.get)
            if event is None:
                break
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    import uvicorn
    uvicorn.run(app, host=host, port=port, log_level="warning")
