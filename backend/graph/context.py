"""What nodes get besides the state: the LLM gateway, the sandbox runner and the media library, passed as the
LangGraph runtime context. Tests pass fakes; `default_context()` builds the real ones.

The context is per execution segment (never checkpointed), so it can hold clients and the current run id.
"""

from dataclasses import dataclass, field
from typing import Any

from langgraph.config import get_stream_writer


@dataclass
class FlowContext:
    run_id: str | None = None
    gateway: Any = None  # .invoke(node_key, messages, snapshot=, schema=, tools=, ...) → GatewayResult
    sandbox: Any = None  # graph.sandbox.SandboxRunner
    media: Any = None  # graph.media.MediaLibrary
    extra: dict = field(default_factory=dict)


def default_context(run_id: str | None = None) -> FlowContext:
    from llm_registry.gateway import Gateway

    from .media import MediaLibrary
    from .sandbox import SandboxRunner

    return FlowContext(run_id=run_id, gateway=Gateway(), sandbox=SandboxRunner(), media=MediaLibrary())


def emit(event: dict) -> None:
    """Send a progress event to whoever streams the graph (the runner publishes it to the run's SSE channel)."""
    try:
        writer = get_stream_writer()
    except RuntimeError:  # called outside a graph run (e.g. a unit test of a helper)
        return
    writer(event)


def warn(message: str) -> list[str]:
    emit({"type": "warning", "message": message})
    return [message]


def llm(runtime, state: dict, node_key: str, messages, *, schema=None, tools=None):
    """Call the node's model chain from the lesson's registry snapshot, forwarding retry/fallback events."""
    return runtime.context.gateway.invoke(
        node_key,
        messages,
        snapshot=state["snapshot"],
        schema=schema,
        tools=tools,
        lesson_id=state.get("lesson_id"),
        run_id=runtime.context.run_id,
        on_event=emit,
    )


def node_settings(state: dict, node_key: str) -> dict:
    """max_attempts / max_tool_steps / enabled for a node, from the lesson's registry snapshot."""
    node = (state.get("snapshot") or {}).get("nodes", {}).get(node_key, {})
    return {
        "enabled": node.get("enabled", True) and bool(node.get("chain")),
        "max_attempts": node.get("max_attempts") or 2,
        "max_tool_steps": node.get("max_tool_steps") or 6,
    }
