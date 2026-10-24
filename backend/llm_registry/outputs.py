"""How the gateway binds a chat model and reads its reply, one OutputAdapter per node output mode (Strategy).

The retry/fallback loop in the gateway is the same for every mode; only binding the model, judging the reply and
(for structured output) asking for a repair differ.
"""

import json
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, ClassVar

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from .node_specs import OutputMode


@dataclass(frozen=True)
class Outcome:
    """What a reply amounted to: a usable output, or the problem with it."""

    ok: bool
    output: Any = None
    message: AIMessage | None = None  # the raw model message, for usage and the call log
    problem: str = ""


class OutputAdapter(ABC):
    mode: ClassVar[OutputMode]

    def check_request(self, node_key: str, schema, tools) -> None:
        """Raise ValueError when the caller didn't pass what this mode needs (a programming error)."""
        return None  # text output needs nothing extra

    @abstractmethod
    def bind(self, chat, *, structured_output_method: str, schema, tools):
        """The runnable to invoke for this mode."""

    @abstractmethod
    def interpret(self, reply) -> Outcome: ...

    def repair_messages(self, messages: Sequence[BaseMessage], outcome: Outcome) -> list[BaseMessage] | None:
        """Messages for one in-place repair attempt after an unusable reply; None when this mode doesn't repair."""
        return None

    @staticmethod
    def text_of(message: AIMessage | None) -> str:
        if message is None:
            return ""
        if message.tool_calls:
            return json.dumps([call["args"] for call in message.tool_calls])
        return message.text if hasattr(message, "text") else str(message.content)


class StructuredOutputAdapter(OutputAdapter):
    """with_structured_output(include_raw=True): a parse failure comes back as data instead of an exception."""

    mode = OutputMode.STRUCTURED

    def check_request(self, node_key: str, schema, tools) -> None:
        if schema is None:
            raise ValueError(f"{node_key} returns structured output; pass schema=")

    def bind(self, chat, *, structured_output_method: str, schema, tools):
        return chat.with_structured_output(schema, method=structured_output_method, include_raw=True)

    def interpret(self, reply) -> Outcome:
        raw, parsed, parse_error = reply.get("raw"), reply.get("parsed"), reply.get("parsing_error")
        if parsed is None:
            problem = str(parse_error) if parse_error else "no structured output was returned"
            return Outcome(ok=False, message=raw, problem=problem)
        return Outcome(ok=True, output=parsed, message=raw)

    def repair_messages(self, messages: Sequence[BaseMessage], outcome: Outcome) -> list[BaseMessage]:
        return [
            *messages,
            AIMessage(content=self.text_of(outcome.message) or "(empty reply)"),
            HumanMessage(
                content=f"Your previous reply did not match the required schema: {outcome.problem}\n"
                "Reply again with output that matches the schema exactly."
            ),
        ]


class ToolsOutputAdapter(OutputAdapter):
    """bind_tools: the reply is the AIMessage with tool calls; the graph runs the tools."""

    mode = OutputMode.TOOLS

    def check_request(self, node_key: str, schema, tools) -> None:
        if not tools:
            raise ValueError(f"{node_key} is a tool-calling node; pass tools=")

    def bind(self, chat, *, structured_output_method: str, schema, tools):
        return chat.bind_tools(tools)

    def interpret(self, reply) -> Outcome:
        return Outcome(ok=True, output=reply, message=reply)


class TextOutputAdapter(OutputAdapter):
    """Plain text, e.g. generated TSX."""

    mode = OutputMode.TEXT

    def bind(self, chat, *, structured_output_method: str, schema, tools):
        return chat

    def interpret(self, reply) -> Outcome:
        return Outcome(ok=True, output=self.text_of(reply), message=reply)


class OutputAdapters:
    """Registry: output mode -> adapter."""

    def __init__(self, adapters: Sequence[OutputAdapter] | None = None):
        adapters = (
            adapters if adapters is not None else (StructuredOutputAdapter(), ToolsOutputAdapter(), TextOutputAdapter())
        )
        self._by_mode = {adapter.mode: adapter for adapter in adapters}

    def for_mode(self, mode: str) -> OutputAdapter:
        return self._by_mode[OutputMode(mode)]


OUTPUT_ADAPTERS = OutputAdapters()
