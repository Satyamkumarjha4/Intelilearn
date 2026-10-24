"""Media subgraph: a tool-calling agent finds an openly licensed image/GIF for one InteractiveSpec.

media_agent ⇄ run_tools        (search_wikimedia · search_openverse · search_gifs)
media_agent → download_and_store → verify_media → done
                    ↑ rejected, attempts left ┘
max tool steps / nothing usable → give_up        (the caller draws an SVG diagram instead)
"""

import base64
import operator
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from .. import prompts
from ..context import FlowContext, emit, llm, node_settings
from ..media import MediaError, MediaSession
from ..schemas import MediaSelection, MediaVerdict


class MediaState(TypedDict, total=False):
    branch: dict  # shared lesson context (Branch)
    spec: dict
    session: Any  # MediaSession (not checkpointed: this subgraph runs without a checkpointer)
    messages: Annotated[list, operator.add]
    steps: int
    rounds: int  # verify/download rounds
    feedback: list[str]
    selection: list[dict]
    ref: dict | None  # MediaRef once stored
    outcome: str  # "found" | "give_up"


def media_agent(state: MediaState, runtime: Runtime[FlowContext]):
    branch, spec = state["branch"], state["spec"]
    session = state["session"]
    sources = branch["settings"].get("media_sources") or ["wikimedia", "openverse"]
    tools = runtime.context.media.tools(session, sources)
    messages = state.get("messages") or []
    new = []
    if not messages:
        names = [t.name for t in tools if t.name != "submit_media"]
        new = prompts.media_agent(branch, spec, names, state.get("feedback"))
    elif state.get("feedback") and isinstance(messages[-1], AIMessage | ToolMessage) and state.get("rounds"):
        new = [HumanMessage("Those candidates were rejected: " + "; ".join(state["feedback"])
                            + " Search again and submit different candidates.")]  # fmt: skip
    result = llm(runtime, branch, "media.search", messages + new, tools=tools)
    return {"messages": [*new, result.output], "steps": state.get("steps", 0) + 1, "feedback": []}


def after_agent(state: MediaState) -> str:
    reply = state["messages"][-1]
    calls = getattr(reply, "tool_calls", None) or []
    if any(call["name"] == "submit_media" for call in calls):
        return "download_and_store"
    limit = node_settings(state["branch"], "media.search")["max_tool_steps"]
    if state.get("steps", 0) >= limit:
        return "give_up"
    return "run_tools" if calls else "nudge"


def nudge(state: MediaState):
    return {"messages": [HumanMessage("Use the search tools, then finish by calling submit_media.")]}


def run_tools(state: MediaState, runtime: Runtime[FlowContext]):
    tools = {t.name: t for t in runtime.context.media.tools(state["session"], ["wikimedia", "openverse", "giphy"])}
    replies = []
    for call in state["messages"][-1].tool_calls:
        tool = tools.get(call["name"])
        try:
            content = tool.invoke(call["args"]) if tool else f"Unknown tool {call['name']}"
        except Exception as exc:  # a failed search is information for the agent, not a crash
            content = f"Search failed: {type(exc).__name__}: {exc}"
        replies.append(ToolMessage(content=str(content)[:6000], tool_call_id=call["id"], name=call["name"]))
    return {"messages": replies}


def download_and_store(state: MediaState, runtime: Runtime[FlowContext]):
    call = next(c for c in state["messages"][-1].tool_calls if c["name"] == "submit_media")
    # Every tool call needs an answer before the conversation can continue.
    ack = ToolMessage(content="received", tool_call_id=call["id"], name="submit_media")
    try:
        candidates = MediaSelection.model_validate(call["args"]).candidates
    except Exception as exc:
        return {"messages": [ack], "feedback": [f"submit_media arguments were invalid: {exc}"], "ref": None,
                "rounds": state.get("rounds", 0) + 1}  # fmt: skip
    library, session, spec = runtime.context.media, state["session"], state["spec"]
    problems = []
    for candidate in candidates:
        seen = session.seen.get(candidate.file_url)
        try:
            content, mime, extension, width, height = library.download(session, candidate.file_url)
        except (MediaError, Exception) as exc:
            problems.append(f"{candidate.title}: {exc}")
            continue
        asset_id, relative = library.store(state["branch"]["lesson_id"], content, extension)
        ref = {
            "asset_id": asset_id, "spec_id": spec["id"], "kind": "gif" if mime == "image/gif" else "image",
            "file": relative, "mime_type": mime, "width": width, "height": height,
            "source": seen["source"], "source_url": seen.get("page_url", ""), "title": seen.get("title", ""),
            "license": seen["license"], "attribution": seen.get("attribution", "")[:500],
            "alt_text": candidate.title, "caption": candidate.title, "verified": False,
            "_b64": base64.b64encode(content).decode() if len(content) < 4_000_000 else "",
        }  # fmt: skip
        return {"messages": [ack], "ref": ref, "feedback": []}
    reason = "; ".join(problems) or "no candidates were submitted"
    return {"messages": [ack], "ref": None, "feedback": [f"None could be used: {reason}"],
            "rounds": state.get("rounds", 0) + 1}  # fmt: skip


def after_download(state: MediaState) -> str:
    if state.get("ref"):
        return "verify_media"
    return "give_up" if state.get("rounds", 0) >= _max_rounds(state) else "media_agent"


def _max_rounds(state) -> int:
    return node_settings(state["branch"], "media.search")["max_attempts"]


def verify_media(state: MediaState, runtime: Runtime[FlowContext]):
    ref = dict(state["ref"])
    encoded = ref.pop("_b64", "")
    branch, spec = state["branch"], state["spec"]
    if not node_settings(branch, "media.verify")["enabled"] or not encoded:
        return {"ref": ref, "outcome": "found"}
    candidate = {"title": ref["title"], "source": ref["source"]}
    messages = prompts.verify_media(branch, spec, candidate, encoded, ref["mime_type"])
    verdict: MediaVerdict = llm(runtime, branch, "media.verify", messages, schema=MediaVerdict).output
    if verdict.approved:
        ref |= {"alt_text": verdict.alt_text, "caption": verdict.caption, "verified": True}
        return {"ref": ref, "outcome": "found"}
    runtime.context.media.discard(ref["file"])
    emit({"type": "attempt", "node": "find_media", "reason": f"image rejected: {verdict.reason}"})
    return {"ref": None, "feedback": [f"{ref['title']}: {verdict.reason}"], "rounds": state.get("rounds", 0) + 1}


def after_verify(state: MediaState) -> str:
    if state.get("outcome") == "found":
        return END
    return "give_up" if state.get("rounds", 0) >= _max_rounds(state) else "media_agent"


def give_up(state: MediaState):
    return {"outcome": "give_up", "ref": None}


def build_media_graph():
    graph = StateGraph(MediaState, context_schema=FlowContext)
    for name, fn in [("media_agent", media_agent), ("run_tools", run_tools), ("nudge", nudge),
                     ("download_and_store", download_and_store), ("verify_media", verify_media),
                     ("give_up", give_up)]:  # fmt: skip
        graph.add_node(name, fn)
    graph.add_edge(START, "media_agent")
    graph.add_conditional_edges("media_agent", after_agent, ["download_and_store", "run_tools", "nudge", "give_up"])
    graph.add_edge("run_tools", "media_agent")
    graph.add_edge("nudge", "media_agent")
    graph.add_conditional_edges("download_and_store", after_download, ["verify_media", "media_agent", "give_up"])
    graph.add_conditional_edges("verify_media", after_verify, [END, "media_agent", "give_up"])
    graph.add_edge("give_up", END)
    return graph.compile()


MEDIA_GRAPH = build_media_graph()


def find_media_for(branch: dict, spec: dict, runtime: Runtime[FlowContext], feedback=None) -> dict | None:
    """Run the subgraph for one spec → MediaRef, or None when nothing suitable was found."""
    allowed = set(branch["settings"].get("allowed_media_licenses") or [])
    session = MediaSession(allowed_licenses=allowed)
    state = MEDIA_GRAPH.invoke(
        {"branch": branch, "spec": spec, "session": session, "feedback": feedback or [], "messages": []},
        context=runtime.context,
        config={"recursion_limit": 60},
    )
    return state.get("ref") if state.get("outcome") == "found" else None
