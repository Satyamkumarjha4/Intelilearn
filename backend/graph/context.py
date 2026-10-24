"""What nodes get besides the state: the ports they depend on, passed as the LangGraph runtime context.

The context is per execution segment (never checkpointed), so it can hold clients and the current run id. Nodes
depend on the small Protocols below; `default_context()` is the composition root that picks the real adapters, and
tests pass fakes.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from langchain_core.messages import BaseMessage
from langgraph.config import get_stream_writer
from pydantic import BaseModel


class EventSink(Protocol):
    def __call__(self, event: dict) -> None:
        """Hand a progress event to whoever streams the run."""


class LLMGateway(Protocol):
    def invoke(
        self,
        node_key: str,
        messages: Sequence[BaseMessage],
        *,
        snapshot: dict,
        schema: type[BaseModel] | None = None,
        tools: Sequence[Any] | None = None,
        lesson_id: Any = None,
        run_id: Any = None,
        on_event: EventSink | None = None,
    ) -> Any:
        """→ an object with `.output` (the parsed schema, a message or text)."""


class CodeSandbox(Protocol):
    def check_code(
        self, code: str, *, required: list[str] = (), components: list[str] = (), asset_ids: list[str] = ()
    ) -> Any: ...

    def latex(self, expressions: list[str]) -> list[str]: ...

    def render_check(self, code: str, data: dict, *, pages: list[str], media_files: dict[str, str]) -> Any: ...


class StreamEventSink:
    """Sends events to LangGraph's custom stream, which the `FlowRunner` relays. Silent outside a graph run."""

    def __call__(self, event: dict) -> None:
        try:
            writer = get_stream_writer()
        except RuntimeError:  # called outside a graph run (a node unit-tested on its own)
            return
        writer(event)


@dataclass(frozen=True)
class NodeBudget:
    """max_attempts / max_tool_steps / enabled for a node, from the lesson's registry snapshot."""

    enabled: bool
    max_attempts: int
    max_tool_steps: int

    @classmethod
    def of(cls, state: dict, node_key: str) -> "NodeBudget":
        node = (state.get("snapshot") or {}).get("nodes", {}).get(node_key, {})
        return cls(
            enabled=node.get("enabled", True) and bool(node.get("chain")),
            max_attempts=node.get("max_attempts") or 2,
            max_tool_steps=node.get("max_tool_steps") or 6,
        )


@dataclass
class FlowContext:
    gateway: LLMGateway
    sandbox: CodeSandbox | None = None
    media: Any = None  # graph.media.MediaLibrary
    events: EventSink | None = None
    run_id: str | None = None

    def __post_init__(self):
        if self.events is None:
            self.events = StreamEventSink()

    def invoke(self, state: dict, node_key: str, messages, *, schema=None, tools=None):
        """Call the node's model chain from the lesson's registry snapshot, forwarding retry/fallback events."""
        return self.gateway.invoke(
            node_key,
            messages,
            snapshot=state["snapshot"],
            schema=schema,
            tools=tools,
            lesson_id=state.get("lesson_id"),
            run_id=self.run_id,
            on_event=self.events,
        )

    def warn(self, message: str) -> list[str]:
        """Tell the learner about a degraded result; returns the list to add to the state's `warnings`."""
        self.events({"type": "warning", "message": message})
        return [message]


def default_context(run_id: str | None = None, events: EventSink | None = None) -> FlowContext:
    """The composition root: the real gateway, sandbox and media library."""
    from llm_registry.gateway import Gateway

    from .media import MediaLibrary
    from .sandbox import SandboxRunner

    return FlowContext(
        gateway=Gateway(), sandbox=SandboxRunner(), media=MediaLibrary.default(), events=events, run_id=run_id
    )
