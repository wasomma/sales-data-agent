"""Replay backend: serves pre-recorded exchanges, never calls an LLM.

This is what the public demo runs on. Answers were recorded once from the real
agent against the synthetic dataset (`sales record-demo`), so the SQL and the
prose are genuine — but serving them costs nothing, consumes no quota, and
cannot be abused by whoever finds the URL.

Questions outside the recorded set get an honest "this is a demo" reply listing
what can be answered, rather than a wrong guess.
"""

import json
import os
import re
import time
from pathlib import Path

from .agent import EventHandler
from .config import PROJECT_ROOT

DEMO_PATH = Path(os.getenv("SALES_AGENT_DEMO_FILE", PROJECT_ROOT / "demo" / "recording.json"))

# Pause between replayed events so the UI's streaming states are visible rather
# than everything landing in one frame. Set SALES_AGENT_REPLAY_DELAY=0 in tests.
STEP_DELAY_S = float(os.getenv("SALES_AGENT_REPLAY_DELAY", "0.7"))

_STOPWORDS = {"the", "a", "an", "of", "in", "for", "is", "are", "my", "me",
              "what", "which", "who", "how", "and", "to", "on", "by", "with"}


def _normalize(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {w for w in words if w not in _STOPWORDS}


def _similarity(a: str, b: str) -> float:
    """Jaccard overlap of significant words — enough to match rephrasings."""
    wa, wb = _normalize(a), _normalize(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


class RecordingNotFound(RuntimeError):
    pass


def load_recording(path: Path | None = None) -> dict:
    path = path or DEMO_PATH
    if not path.exists():
        raise RecordingNotFound(
            f"No demo recording at {path}. Create one with: sales record-demo"
        )
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class ReplayBackend:
    """Same interface as the live backends: .ask(), .reset(), .on_event."""

    MATCH_THRESHOLD = 0.55

    def __init__(self, console=None, show_sql: bool = True,
                 on_event: EventHandler | None = None, recording: dict | None = None):
        self.console = console
        self.show_sql = show_sql
        self.on_event = on_event
        self.recording = recording or load_recording()
        self.exchanges = self.recording.get("exchanges", [])

    @property
    def questions(self) -> list[str]:
        return [e["question"] for e in self.exchanges]

    def reset(self) -> None:
        """Nothing to reset — replay is stateless."""

    def _emit(self, event: dict) -> None:
        if self.on_event is not None:
            self.on_event(event)

    def _match(self, question: str) -> dict | None:
        best, best_score = None, 0.0
        for exchange in self.exchanges:
            score = _similarity(question, exchange["question"])
            if score > best_score:
                best, best_score = exchange, score
        return best if best_score >= self.MATCH_THRESHOLD else None

    def ask(self, question: str) -> str:
        exchange = self._match(question)
        if exchange is None:
            listed = "\n".join(f"- {q}" for q in self.questions)
            return ("This is a **demo** running on pre-recorded answers, so it can only "
                    "respond to a fixed set of questions. Try one of these:\n\n" + listed +
                    "\n\nThe full version answers anything by querying the database live.")

        for event in exchange.get("events", []):
            if STEP_DELAY_S:
                time.sleep(STEP_DELAY_S)
            self._emit(event)
        if STEP_DELAY_S:
            time.sleep(STEP_DELAY_S)
        return exchange["answer"]
