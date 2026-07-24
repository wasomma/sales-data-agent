"""LLM provider abstraction.

The agent loop (agent.py) is provider-agnostic: a provider takes the running
conversation plus tool definitions and returns a normalized turn — text and/or
tool calls. ClaudeProvider is the current implementation; a GeminiProvider will
be added here when the company Gemini key is available, with no changes to the
agent loop, tools, or CLI.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol

import anthropic

from .config import MAX_TOKENS, MODEL


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


def get_provider() -> LLMProvider:
    # Later: branch on SALES_AGENT_PROVIDER to return GeminiProvider.
    return ClaudeProvider()
