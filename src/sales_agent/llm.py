"""LLM provider abstraction.

The agent loop (agent.py) is provider-agnostic: a provider takes the running
conversation plus tool definitions and returns a normalized turn — text and/or
tool calls. Both ClaudeProvider and GeminiProvider live here, selected by
SALES_AGENT_PROVIDER, with no changes to the agent loop, tools, or CLI.

One asymmetry to know about: Anthropic pairs a tool result to its call by id,
Gemini pairs it by function *name*. The normalized ToolCall carries an id
either way, so GeminiProvider keeps an id-to-name map across the turn and
resolves it when building the results message.
"""

import os
from dataclasses import dataclass, field
from typing import Any, Protocol

import anthropic

from .config import GEMINI_MODEL, MAX_TOKENS, MODEL


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict


@dataclass
class Turn:
    """Normalized model output for one assistant turn."""
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = ""
    raw_content: Any = None  # provider-native content, echoed back verbatim


class LLMProvider(Protocol):
    def send(self, system: str, messages: list[dict], tools: list[dict]) -> Turn: ...

    def tool_results_message(self, results: list[tuple[str, str]]) -> dict:
        """Build the provider-native message carrying [(tool_call_id, result), ...]."""
        ...

    def assistant_message(self, turn: Turn) -> dict: ...


class ClaudeProvider:
    """Claude via the Anthropic SDK, with native tool use.

    Uses the beta messages endpoint to opt into server-side refusal fallbacks
    (fallbacks="default"): if a safety classifier declines a request, the API
    transparently re-runs it on the recommended fallback model instead of
    returning an empty refusal.
    """

    def __init__(self, model: str = MODEL):
        self.client = anthropic.Anthropic()
        self.model = model

    def send(self, system: str, messages: list[dict], tools: list[dict]) -> Turn:
        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            tools=tools,
            messages=messages,
            betas=["server-side-fallback-2026-07-01"],
            extra_body={"fallbacks": "default"},
        )
        turn = Turn(stop_reason=response.stop_reason or "", raw_content=response.content)
        if response.stop_reason == "refusal":
            turn.text = "The model declined to answer this request."
            return turn
        for block in response.content:
            if block.type == "text":
                turn.text += block.text
            elif block.type == "tool_use":
                turn.tool_calls.append(ToolCall(id=block.id, name=block.name, input=block.input))
        return turn

    def tool_results_message(self, results: list[tuple[str, str]]) -> dict:
        return {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": call_id, "content": result}
                for call_id, result in results
            ],
        }

    def assistant_message(self, turn: Turn) -> dict:
        return {"role": "assistant", "content": turn.raw_content}


class GeminiProvider:
    """Gemini via the google-genai SDK, with native function calling.

    Automatic function calling is switched off deliberately: agent.py runs the
    tool loop itself so the executed SQL can be surfaced to the user, and the
    same loop has to work identically for every provider.
    """

    def __init__(self, model: str = GEMINI_MODEL):
        from google import genai

        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Put it in .env (which is gitignored) "
                "or set it in the environment."
            )
        self.client = genai.Client(api_key=api_key)
        self.model = model
        # Gemini matches a tool result to its call by name, not id.
        self._names: dict[str, str] = {}

    def _contents(self, messages: list[Any]) -> list[Any]:
        """Normalize the running conversation into google-genai Contents.

        Only the first message is foreign — agent.py appends the question as a
        plain {"role", "content"} dict. Everything after it came from this
        provider's own assistant_message/tool_results_message and is already a
        Content, so it passes straight through.
        """
        from google.genai import types

        out = []
        for message in messages:
            if isinstance(message, types.Content):
                out.append(message)
                continue
            content = message["content"]
            if isinstance(content, str):
                out.append(types.Content(role=message.get("role", "user"),
                                         parts=[types.Part(text=content)]))
            else:
                out.append(content)
        return out

    def send(self, system: str, messages: list[dict], tools: list[dict]) -> Turn:
        from google.genai import types

        declarations = [
            types.FunctionDeclaration(
                name=tool["name"],
                description=tool["description"],
                # The tool schemas are already JSON Schema, so hand them over
                # verbatim rather than re-describing them in Gemini's dialect.
                parameters_json_schema=tool["input_schema"],
            )
            for tool in tools
        ]
        config = types.GenerateContentConfig(
            system_instruction=system,
            tools=[types.Tool(function_declarations=declarations)],
            max_output_tokens=MAX_TOKENS,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        response = self.client.models.generate_content(
            model=self.model, contents=self._contents(messages), config=config,
        )

        candidates = response.candidates or []
        if not candidates or candidates[0].content is None:
            reason = candidates[0].finish_reason if candidates else "no candidates"
            return Turn(text=f"Gemini returned no content (finish reason: {reason}).",
                        stop_reason=str(reason))

        candidate = candidates[0]
        turn = Turn(stop_reason=str(candidate.finish_reason or ""),
                    raw_content=candidate.content)
        for index, part in enumerate(candidate.content.parts or []):
            if part.text:
                turn.text += part.text
            call = part.function_call
            if call is not None:
                # id is optional on the wire; synthesize a stable one so the
                # normalized ToolCall keeps the same contract as Anthropic's.
                call_id = call.id or f"{call.name}-{index}"
                self._names[call_id] = call.name
                turn.tool_calls.append(
                    ToolCall(id=call_id, name=call.name, input=dict(call.args or {})))
        return turn

    def tool_results_message(self, results: list[tuple[str, str]]) -> dict:
        from google.genai import types

        return types.Content(
            role="user",
            parts=[
                types.Part.from_function_response(
                    name=self._names.get(call_id, call_id),
                    response={"result": result},
                )
                for call_id, result in results
            ],
        )

    def assistant_message(self, turn: Turn) -> dict:
        return turn.raw_content


def get_provider() -> LLMProvider:
    """Pick a provider from SALES_AGENT_PROVIDER, defaulting to Claude."""
    provider = (os.getenv("SALES_AGENT_PROVIDER") or "").lower()
    if provider == "gemini":
        return GeminiProvider()
    return ClaudeProvider()
