"""GeminiProvider translation logic, without touching the network.

The risk in this provider is not the API call, it is the shape-shifting around
it: agent.py speaks one normalized dialect, Anthropic pairs tool results by id,
and Gemini pairs them by function name. These tests pin the translation so a
live run only has to prove the network path.
"""

import pytest

from sales_agent.llm import GeminiProvider, Turn, get_provider
from sales_agent.tools import TOOL_DEFINITIONS

genai_types = pytest.importorskip("google.genai.types")


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    return GeminiProvider(model="gemini-test")


class _FakeModels:
    def __init__(self, response):
        self.response = response
        self.kwargs = None

    def generate_content(self, **kwargs):
        self.kwargs = kwargs
        return self.response


class _FakeClient:
    def __init__(self, response):
        self.models = _FakeModels(response)


class _FakeCandidate:
    def __init__(self, content, finish_reason="STOP"):
        self.content = content
        self.finish_reason = finish_reason


class _FakeResponse:
    def __init__(self, candidates):
        self.candidates = candidates


def _model_turn(parts):
    return _FakeResponse([_FakeCandidate(genai_types.Content(role="model", parts=parts))])


# --- conversation translation ------------------------------------------------

def test_plain_question_becomes_a_text_content(provider):
    """agent.py appends the question as a bare dict; everything else is native."""
    out = provider._contents([{"role": "user", "content": "how many deals?"}])
    assert len(out) == 1
    assert out[0].role == "user"
    assert out[0].parts[0].text == "how many deals?"


def test_native_contents_pass_through_untouched(provider):
    native = genai_types.Content(role="model", parts=[genai_types.Part(text="hi")])
    assert provider._contents([native])[0] is native


# --- request construction ----------------------------------------------------

def test_tool_schemas_are_forwarded_verbatim(provider):
    """Gemini accepts JSON Schema directly, so the tool definitions must not be
    rewritten into a second dialect that could drift from the originals."""
    provider.client = _FakeClient(_model_turn([genai_types.Part(text="ok")]))
    provider.send("system", [{"role": "user", "content": "q"}], TOOL_DEFINITIONS)

    declarations = provider.client.models.kwargs["config"].tools[0].function_declarations
    assert {d.name for d in declarations} == {t["name"] for t in TOOL_DEFINITIONS}
    run_sql = next(d for d in declarations if d.name == "run_sql")
    assert run_sql.parameters_json_schema["required"] == ["query"]


def test_automatic_function_calling_is_disabled(provider):
    """agent.py owns the tool loop — the SDK must not run one of its own."""
    provider.client = _FakeClient(_model_turn([genai_types.Part(text="ok")]))
    provider.send("system", [{"role": "user", "content": "q"}], TOOL_DEFINITIONS)
    config = provider.client.models.kwargs["config"]
    assert config.automatic_function_calling.disable is True


# --- response parsing --------------------------------------------------------

def test_text_and_tool_calls_are_both_captured(provider):
    parts = [
        genai_types.Part(text="Let me check. "),
        genai_types.Part(function_call=genai_types.FunctionCall(
            name="run_sql", args={"query": "SELECT 1"})),
    ]
    provider.client = _FakeClient(_model_turn(parts))
    turn = provider.send("system", [{"role": "user", "content": "q"}], TOOL_DEFINITIONS)
    assert turn.text == "Let me check. "
    assert len(turn.tool_calls) == 1
    assert turn.tool_calls[0].name == "run_sql"
    assert turn.tool_calls[0].input == {"query": "SELECT 1"}


def test_missing_content_is_reported_not_crashed(provider):
    """A safety stop or token cap yields a candidate with no content."""
    provider.client = _FakeClient(_FakeResponse([_FakeCandidate(None, "MAX_TOKENS")]))
    turn = provider.send("system", [{"role": "user", "content": "q"}], TOOL_DEFINITIONS)
    assert "MAX_TOKENS" in turn.text
    assert turn.tool_calls == []


def test_no_candidates_is_reported_not_crashed(provider):
    provider.client = _FakeClient(_FakeResponse([]))
    turn = provider.send("system", [{"role": "user", "content": "q"}], TOOL_DEFINITIONS)
    assert "no content" in turn.text.lower()


# --- the id/name asymmetry ---------------------------------------------------

def test_tool_results_are_addressed_by_function_name(provider):
    """Anthropic pairs a result to its call by id, Gemini by name. agent.py hands
    back ids, so the provider must resolve them or the model sees an orphan."""
    parts = [genai_types.Part(function_call=genai_types.FunctionCall(
        name="get_schema", args={}))]
    provider.client = _FakeClient(_model_turn(parts))
    turn = provider.send("system", [{"role": "user", "content": "q"}], TOOL_DEFINITIONS)

    call_id = turn.tool_calls[0].id
    message = provider.tool_results_message([(call_id, "deals_current(...)")])
    assert message.parts[0].function_response.name == "get_schema"
    assert message.parts[0].function_response.response == {"result": "deals_current(...)"}


def test_parallel_calls_to_one_tool_keep_distinct_ids(provider):
    parts = [
        genai_types.Part(function_call=genai_types.FunctionCall(
            name="run_sql", args={"query": "SELECT 1"})),
        genai_types.Part(function_call=genai_types.FunctionCall(
            name="run_sql", args={"query": "SELECT 2"})),
    ]
    provider.client = _FakeClient(_model_turn(parts))
    turn = provider.send("system", [{"role": "user", "content": "q"}], TOOL_DEFINITIONS)
    ids = [c.id for c in turn.tool_calls]
    assert len(set(ids)) == 2
    message = provider.tool_results_message([(i, "rows") for i in ids])
    assert [p.function_response.name for p in message.parts] == ["run_sql", "run_sql"]


def test_unknown_id_falls_back_rather_than_raising(provider):
    message = provider.tool_results_message([("never-seen", "result")])
    assert message.parts[0].function_response.name == "never-seen"


def test_assistant_message_echoes_the_native_content(provider):
    native = genai_types.Content(role="model", parts=[genai_types.Part(text="hi")])
    assert provider.assistant_message(Turn(raw_content=native)) is native


# --- selection ---------------------------------------------------------------

def test_provider_selected_by_env(monkeypatch):
    monkeypatch.setenv("SALES_AGENT_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    assert isinstance(get_provider(), GeminiProvider)


def test_missing_key_fails_with_a_usable_message(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        GeminiProvider()
