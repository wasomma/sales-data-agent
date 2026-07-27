"""Antigravity (Gemini) backend: event parsing, setup wiring, backend selection.

The stream-json tool-call payload is the least-pinned part of this integration —
agy nests it differently across versions and may hand arguments over as a dict
or as a JSON string. _find_sql is deliberately shape-agnostic, so these cases
are the contract: if a future agy version nests the query somewhere new, add the
shape here rather than reaching into the event by a fixed path.
"""

import json

import pytest

from sales_agent import agy_setup, backend as backend_mod
from sales_agent.antigravity import AntigravityBackend, _find_sql

SQL = "SELECT stage, SUM(amount) FROM deals_current GROUP BY stage"


def test_finds_sql_in_nested_dict_args():
    event = {"event": "step_update", "step_update": {
        "step_type": "tool_call",
        "tool": {"name": "call_mcp_tool", "args": {"query": SQL}}}}
    assert _find_sql(event) == [SQL]


def test_finds_sql_when_args_are_a_json_string():
    event = {"event": "step_update", "step_update": {
        "tool_call": {"name": "call_mcp_tool",
                      "arguments": json.dumps({"server": "sales", "query": SQL})}}}
    assert _find_sql(event) == [SQL]


def test_finds_sql_in_a_list_of_tool_calls():
    event = {"event": "step_update", "step_update": {
        "tool_calls": [{"args": {"query": SQL}}]}}
    assert _find_sql(event) == [SQL]


def test_ignores_non_sql_query_fields():
    """Plenty of unrelated payloads carry a 'query' key — a web search, say."""
    event = {"event": "step_update", "step_update": {
        "tool": {"name": "search_web", "args": {"query": "how to write duckdb sql"}}}}
    assert _find_sql(event) == []


def test_result_event_returns_response_and_captures_conversation_id(monkeypatch):
    monkeypatch.setattr("sales_agent.antigravity.find_agy", lambda: "agy")
    b = AntigravityBackend()
    out = b._handle_event(
        {"event": "result",
         "result": {"conversation_id": "abc-123", "status": "SUCCESS", "response": "42 deals."}},
        set())
    assert out == "42 deals."
    assert b.conversation_id == "abc-123"


def test_failed_result_is_reported_as_an_error_answer(monkeypatch):
    monkeypatch.setattr("sales_agent.antigravity.find_agy", lambda: "agy")
    b = AntigravityBackend()
    out = b._handle_event(
        {"event": "result", "result": {"status": "ERROR", "error": "quota exceeded"}}, set())
    assert backend_mod.is_error_answer(out)


def test_repeated_step_updates_emit_each_query_once(monkeypatch):
    """step_update streams incrementally, so the same call arrives many times."""
    monkeypatch.setattr("sales_agent.antigravity.find_agy", lambda: "agy")
    events = []
    b = AntigravityBackend(on_event=events.append)
    seen = set()
    payload = {"event": "step_update", "step_update": {"tool": {"args": {"query": SQL}}}}
    for _ in range(3):
        b._handle_event(payload, seen)
    assert events == [{"type": "sql", "query": SQL}]


def test_system_prompt_rides_the_first_question_only(monkeypatch):
    monkeypatch.setattr("sales_agent.antigravity.find_agy", lambda: "agy")
    b = AntigravityBackend()
    first = b._prompt("how many deals?")
    assert "sales-data analyst agent" in first and "how many deals?" in first
    b.conversation_id = "abc-123"
    assert b._prompt("and by stage?") == "and by stage?"


def test_resume_passes_the_conversation_id(monkeypatch):
    monkeypatch.setattr("sales_agent.antigravity.find_agy", lambda: "agy")
    b = AntigravityBackend()
    assert "--conversation" not in b._command("q")
    b.conversation_id = "abc-123"
    cmd = b._command("q")
    assert cmd[cmd.index("--conversation") + 1] == "abc-123"


def test_reset_starts_a_new_conversation(monkeypatch):
    monkeypatch.setattr("sales_agent.antigravity.find_agy", lambda: "agy")
    b = AntigravityBackend()
    b.conversation_id = "abc-123"
    b.reset()
    assert b.conversation_id is None


# --- setup wiring -----------------------------------------------------------

@pytest.fixture
def tmp_config(tmp_path, monkeypatch):
    path = tmp_path / "mcp_config.json"
    monkeypatch.setattr(agy_setup, "MCP_CONFIG_PATH", path)
    return path


def test_install_preserves_other_mcp_servers(tmp_config):
    agy_setup.write_json(tmp_config, {"mcpServers": {"chrome_devtools": {"command": "chrome-mcp"}}})
    agy_setup.install_server()
    servers = json.loads(tmp_config.read_text(encoding="utf-8"))["mcpServers"]
    assert "chrome_devtools" in servers  # never clobber a shared config
    assert servers["sales"] == agy_setup.server_entry()


def test_install_writes_without_a_bom(tmp_config):
    """A BOM makes agy silently load no MCP servers at all."""
    agy_setup.install_server()
    assert not tmp_config.read_bytes().startswith(b"\xef\xbb\xbf")


def test_install_is_idempotent(tmp_config):
    agy_setup.install_server()
    changed, _ = agy_setup.install_server()
    assert changed is False


def test_read_json_tolerates_empty_and_bom_files(tmp_config):
    tmp_config.write_bytes(b"")
    assert agy_setup.read_json(tmp_config) == {}
    tmp_config.write_bytes(b"\xef\xbb\xbf" + b'{"mcpServers": {}}')
    assert agy_setup.read_json(tmp_config) == {"mcpServers": {}}


def test_apply_permissions_keeps_existing_rules(tmp_path, monkeypatch):
    settings = tmp_path / "settings.json"
    monkeypatch.setattr(agy_setup, "SETTINGS_PATH", settings)
    agy_setup.write_json(settings, {"enableTelemetry": False,
                                    "permissions": {"allow": ["command(agy help models)"]}})
    added, _ = agy_setup.apply_permissions()
    result = json.loads(settings.read_text(encoding="utf-8"))
    assert "command(agy help models)" in result["permissions"]["allow"]
    assert agy_setup.ALLOW_RULE in result["permissions"]["allow"]
    assert result["enableTelemetry"] is False  # unrelated settings survive
    assert agy_setup.ALLOW_RULE in added


def test_broad_mcp_wildcard_counts_as_allowed(tmp_path, monkeypatch):
    settings = tmp_path / "settings.json"
    monkeypatch.setattr(agy_setup, "SETTINGS_PATH", settings)
    agy_setup.write_json(settings, {"permissions": {"allow": ["mcp(*)"], "deny": ["command(*)"]}})
    assert agy_setup.missing_permissions() == []


# --- backend selection ------------------------------------------------------

def test_agy_is_opt_in_only(monkeypatch):
    """A machine with agy installed must not silently start routing data to it."""
    monkeypatch.delenv("SALES_AGENT_BACKEND", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert backend_mod.backend_name() == "Claude subscription"


def test_agy_selected_by_env(monkeypatch):
    monkeypatch.setenv("SALES_AGENT_BACKEND", "agy")
    assert backend_mod.backend_name() == "Gemini (Antigravity)"


def test_replay_still_wins_over_everything(monkeypatch):
    """The public demo must never reach a live backend."""
    monkeypatch.setenv("SALES_AGENT_BACKEND", "replay")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert backend_mod.is_replay()
    assert backend_mod.backend_name() == "Demo — recorded answers"
