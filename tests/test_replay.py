"""Replay backend: matching, fallback, and event emission."""

import pytest

from sales_agent import replay
from sales_agent.replay import ReplayBackend

RECORDING = {
    "recorded": "2026-07-26",
    "exchanges": [
        {
            "question": "Total pipeline by stage",
            "events": [{"type": "sql", "query": "SELECT stage, SUM(amount) FROM deals_current GROUP BY stage"}],
            "answer": "Prospecting leads at $6.11M.",
        },
        {
            "question": "What are my top 10 largest deals closing in 2026?",
            "events": [{"type": "tool", "name": "get_schema"},
                       {"type": "sql", "query": "SELECT * FROM deals_current LIMIT 10"}],
            "answer": "Keystone Pharma tops the list.",
        },
    ],
}


@pytest.fixture(autouse=True)
def no_delay(monkeypatch):
    monkeypatch.setattr(replay, "STEP_DELAY_S", 0)


@pytest.fixture
def backend():
    return ReplayBackend(recording=RECORDING)


def test_exact_question_replays_answer_and_events(backend):
    events = []
    backend.on_event = events.append
    answer = backend.ask("Total pipeline by stage")
    assert answer == "Prospecting leads at $6.11M."
    assert events == RECORDING["exchanges"][0]["events"]


def test_rephrasing_still_matches(backend):
    answer = backend.ask("what is the total pipeline by stage?")
    assert answer == "Prospecting leads at $6.11M."


def test_unrecorded_question_gets_honest_fallback(backend):
    events = []
    backend.on_event = events.append
    answer = backend.ask("How many employees does the company have?")
    assert "demo" in answer.lower()
    assert "Total pipeline by stage" in answer  # lists what it can answer
    assert events == []  # no fabricated SQL for a question it cannot answer


def test_near_miss_does_not_match_wrong_exchange(backend):
    """A question sharing a couple of words must not return an unrelated answer."""
    answer = backend.ask("largest deals")
    assert "Keystone" in answer or "demo" in answer.lower()


def test_reset_is_a_noop(backend):
    backend.reset()
    assert backend.ask("Total pipeline by stage").startswith("Prospecting")


def test_questions_property_lists_recorded_questions(backend):
    assert backend.questions == [e["question"] for e in RECORDING["exchanges"]]
