"""The media subgraph: a tool-calling agent finds an openly licensed image or GIF for one `InteractiveSpec`.

    media_agent ⇄ run_tools                      (the search tools)
    media_agent → download_and_store → verify_media → done
                        ↑ rejected, attempts left ┘
    too many tool steps, or nothing usable → give_up   (the caller draws an SVG diagram instead)

It runs inside the `find_media` node, without a checkpointer: the session (which URLs the tools returned) is not
JSON, and a half-finished search is cheap to start again.
"""

import base64
import operator
from typing import Annotated, Any, TypedDict

from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from ..builder_base import GraphBuilder
from ..context import FlowContext, NodeBudget
from ..media import MediaError, MediaSession
from ..prompts import MediaAgentPrompt, VerifyMediaPrompt
from ..schemas import MediaSelection, MediaVerdict
from .base import Node
from .routers import Router


class MediaState(TypedDict, total=False):
    branch: dict  # the lesson context of the widget (a `Branch`)
    spec: dict
    session: Any  # MediaSession
    messages: Annotated[list, operator.add]
    steps: int
    rounds: int  # download/verify rounds that found nothing
    feedback: list[str]
    ref: dict | None  # the MediaRef once stored
    outcome: str  # "found" | "give_up"


def sources_of(branch: dict) -> list[str]:
    return branch["settings"].get("media_sources") or ["wikimedia", "openverse"]


class MediaAgentNode(Node):
    name = "media_agent"

    def run(self, state: MediaState, ctx: FlowContext) -> dict:
        branch, spec, session = state["branch"], state["spec"], state["session"]
        tools = ctx.media.tools(session, sources_of(branch))
        messages = state.get("messages") or []
        new: list = []
        if not messages:
            names = [t.name for t in tools if t.name != "submit_media"]
            new = MediaAgentPrompt().messages(branch | {"spec": spec, "tools_available": names}, state.get("feedback"))
        elif state.get("feedback") and state.get("rounds"):
            rejected = "; ".join(state["feedback"])
            new = [
                HumanMessage(
                    f"Those candidates were rejected: {rejected}. Search again and submit different candidates."
                )
            ]
        result = ctx.invoke(branch, "media.search", messages + new, tools=tools)
        return {"messages": [*new, result.output], "steps": state.get("steps", 0) + 1, "feedback": []}


class AgentRouter(Router):
    def __call__(self, state: MediaState) -> str:
        calls = getattr(state["messages"][-1], "tool_calls", None) or []
        if any(call["name"] == "submit_media" for call in calls):
            return "download_and_store"
        if state.get("steps", 0) >= NodeBudget.of(state["branch"], "media.search").max_tool_steps:
            return "give_up"
        return "run_tools" if calls else "nudge"


class NudgeNode(Node):
    name = "nudge"

    def run(self, state: MediaState, ctx: FlowContext) -> dict:
        return {"messages": [HumanMessage("Use the search tools, then finish by calling submit_media.")]}


class RunToolsNode(Node):
    name = "run_tools"

    def run(self, state: MediaState, ctx: FlowContext) -> dict:
        tools = {t.name: t for t in ctx.media.tools(state["session"], sources_of(state["branch"]))}
        replies = []
        for call in state["messages"][-1].tool_calls:
            tool = tools.get(call["name"])
            try:
                content = tool.invoke(call["args"]) if tool else f"Unknown tool {call['name']}"
            except Exception as exc:  # a failed search is information for the agent, not a crash
                content = f"Search failed: {type(exc).__name__}: {exc}"
            replies.append(ToolMessage(content=str(content)[:6000], tool_call_id=call["id"], name=call["name"]))
        return {"messages": replies}


class DownloadAndStoreNode(Node):
    name = "download_and_store"
    MAX_ENCODED_BYTES = 4_000_000  # larger files are stored but not sent to the vision model

    def encoded(self, content: bytes) -> str:
        return base64.b64encode(content).decode() if len(content) < self.MAX_ENCODED_BYTES else ""

    def run(self, state: MediaState, ctx: FlowContext) -> dict:
        call = next(c for c in state["messages"][-1].tool_calls if c["name"] == "submit_media")
        ack = ToolMessage(content="received", tool_call_id=call["id"], name="submit_media")  # every call needs a reply
        rounds = state.get("rounds", 0) + 1
        try:
            candidates = MediaSelection.model_validate(call["args"]).candidates
        except Exception as exc:
            return {
                "messages": [ack],
                "feedback": [f"submit_media arguments were invalid: {exc}"],
                "ref": None,
                "rounds": rounds,
            }
        session, spec = state["session"], state["spec"]
        problems = []
        for candidate in candidates:
            try:
                download = ctx.media.download(session, candidate.file_url)
            except MediaError as exc:
                problems.append(f"{candidate.title}: {exc}")
                continue
            seen = session.seen[candidate.file_url]
            stored = ctx.media.store(state["branch"]["lesson_id"], download.content, download.extension)
            ref = {
                "asset_id": stored.asset_id, "spec_id": spec["id"],
                "kind": "gif" if download.mime == "image/gif" else "image", "file": stored.relative,
                "mime_type": download.mime, "width": download.width, "height": download.height,
                "source": seen["source"], "source_url": seen.get("page_url", ""), "title": seen.get("title", ""),
                "license": seen["license"], "attribution": seen.get("attribution", "")[:500],
                "alt_text": candidate.title, "caption": candidate.title, "verified": False,
                "_b64": self.encoded(download.content),
            }  # fmt: skip
            return {"messages": [ack], "ref": ref, "feedback": []}
        reason = "; ".join(problems) or "no candidates were submitted"
        return {"messages": [ack], "ref": None, "feedback": [f"None could be used: {reason}"], "rounds": rounds}


class DownloadRouter(Router):
    def __call__(self, state: MediaState) -> str:
        if state.get("ref"):
            return "verify_media"
        return (
            "give_up"
            if state.get("rounds", 0) >= NodeBudget.of(state["branch"], "media.search").max_attempts
            else "media_agent"
        )


class VerifyMediaNode(Node):
    """The optional `media.verify` vision check: does the picture show what the spec needs, and write its alt text."""

    name = "verify_media"

    def run(self, state: MediaState, ctx: FlowContext) -> dict:
        ref = dict(state["ref"])
        encoded = ref.pop("_b64", "")
        branch, spec = state["branch"], state["spec"]
        if not NodeBudget.of(branch, "media.verify").enabled or not encoded:
            return {"ref": ref, "outcome": "found"}
        subject = branch | {
            "spec": spec, "candidate": {"title": ref["title"], "source": ref["source"]}, "image_b64": encoded,
            "mime": ref["mime_type"],
        }  # fmt: skip
        verdict: MediaVerdict = ctx.invoke(
            branch, "media.verify", VerifyMediaPrompt().messages(subject), schema=MediaVerdict
        ).output
        if verdict.approved:
            return {
                "ref": ref | {"alt_text": verdict.alt_text, "caption": verdict.caption, "verified": True},
                "outcome": "found",
            }
        ctx.media.discard(ref["file"])
        ctx.events({"type": "attempt", "node": "find_media", "reason": f"image rejected: {verdict.reason}"})
        return {"ref": None, "feedback": [f"{ref['title']}: {verdict.reason}"], "rounds": state.get("rounds", 0) + 1}


class VerifyRouter(Router):
    def __call__(self, state: MediaState) -> str:
        if state.get("outcome") == "found":
            return END
        return (
            "give_up"
            if state.get("rounds", 0) >= NodeBudget.of(state["branch"], "media.search").max_attempts
            else "media_agent"
        )


class GiveUpNode(Node):
    name = "give_up"

    def run(self, state: MediaState, ctx: FlowContext) -> dict:
        return {"outcome": "give_up", "ref": None}


class MediaGraphBuilder(GraphBuilder):
    state_schema = MediaState

    def add_nodes(self, graph: StateGraph) -> None:
        for node in (
            MediaAgentNode(),
            RunToolsNode(),
            NudgeNode(),
            DownloadAndStoreNode(),
            VerifyMediaNode(),
            GiveUpNode(),
        ):
            graph.add_node(node.name, node)

    def add_edges(self, graph: StateGraph) -> None:
        graph.add_edge(START, "media_agent")
        graph.add_conditional_edges(
            "media_agent", AgentRouter(), ["download_and_store", "run_tools", "nudge", "give_up"]
        )
        graph.add_edge("run_tools", "media_agent")
        graph.add_edge("nudge", "media_agent")
        graph.add_conditional_edges("download_and_store", DownloadRouter(), ["verify_media", "media_agent", "give_up"])
        graph.add_conditional_edges("verify_media", VerifyRouter(), [END, "media_agent", "give_up"])
        graph.add_edge("give_up", END)


class MediaFinder:
    """Runs the media subgraph for one spec → a MediaRef, or None when nothing suitable was found."""

    RECURSION_LIMIT = 60

    def __init__(self, builder: GraphBuilder | None = None):
        self.graph = (builder or MediaGraphBuilder()).build()

    def find(self, ctx: FlowContext, branch: dict, spec: dict, feedback: list[str] | None = None) -> dict | None:
        session = MediaSession(allowed_licenses=set(branch["settings"].get("allowed_media_licenses") or []))
        state = self.graph.invoke(
            {"branch": branch, "spec": spec, "session": session, "feedback": feedback or [], "messages": []},
            context=ctx,
            config={"recursion_limit": self.RECURSION_LIMIT},
        )
        return state.get("ref") if state.get("outcome") == "found" else None
