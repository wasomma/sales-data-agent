"""MCP tool robustness: a malformed call must stay recoverable.

Antigravity ends the whole run when a tool *call* fails validation, but hands a
tool *result* back to the model to correct. Gemini occasionally emits run_sql
with empty Arguments, so the difference between those two decides whether one
bad call costs a question or a retry. These tests pin the recoverable behaviour.
"""

import pytest

from sales_agent.mcp_server import run_sql
from sales_agent.tools import TOOL_DEFINITIONS


@pytest.mark.parametrize("missing", ["", "   ", "\n\t "])
def test_missing_query_returns_correctable_text(missing):
    """Must return, not raise — a raise becomes a fatal validation error."""
    result = run_sql(missing)
    assert result.startswith("Error:")
    assert "query" in result


def test_missing_query_is_callable_without_arguments():
    """FastMCP derives the schema from the signature, so the default is what
    stops pydantic rejecting an argument-less call before our code runs."""
    assert run_sql().startswith("Error:")


def test_error_text_shows_the_shape_to_retry_with():
    """The model has to be able to fix itself from this string alone."""
    result = run_sql("")
    assert "SELECT" in result


def test_query_is_still_advertised_as_required():
    """The default is a safety net, not a relaxation of the contract — the API
    backend's schema must keep demanding a query."""
    run_sql_def = next(t for t in TOOL_DEFINITIONS if t["name"] == "run_sql")
    assert run_sql_def["input_schema"]["required"] == ["query"]
