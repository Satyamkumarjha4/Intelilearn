"""Unit under test: the media subgraph in `graph.nodes.media_agent` (`MediaGraphBuilder`, its nodes and `MediaFinder`):
a tool-calling agent that finds an openly licensed image or GIF for one interactive spec.

Why: it is the one place a model's output decides which file the server downloads and shows a learner. It must only
ever download what a search tool returned, stop searching after a bounded number of steps, recover from a failed
search or a rejected picture, and end with either a stored, attributed file or a clean "nothing suitable" that lets
the lesson draw a diagram instead of leaving a hole.

Use cases:
- search, submit, download and store: a MediaRef with the file stored, licence, attribution and the source page kept
- the optional vision check approves (alt text and caption from the verdict, verified) or rejects (file removed, the
  agent searches again with the reason, and the next candidate can be approved)
- the vision check is skipped when the node has no model, and a picture it cannot judge because every vision model
  failed is kept unverified with a warning instead of failing the lesson
- a candidate whose URL no tool returned, or that fails the download guards, is reported back and the agent tries again
- out of rounds it gives up, and so does an agent that keeps searching past the tool-step cap
- a reply with no tool call is nudged to use the tools
- a search that raises is reported to the agent as information, not a crash
- invalid submit_media arguments are reported back
- the finder returns the ref, or None when the agent gave up, and starts every spec with a fresh session
"""

import json

import pytest
from langchain_core.messages import AIMessage
from support.media import make_library, png, result

from graph.media import MediaError
from graph.nodes.media_agent import MediaFinder, MediaGraphBuilder
from graph.schemas import InteractiveSpec
from llm_registry.gateway import AllModelsFailed

SPEC = InteractiveSpec(
    id="amoeba", page="introduction", anchor_section="s1", kind="image", purpose="Shows binary fission clearly.",
    description="A real amoeba dividing", media_query="amoeba binary fission",
).model_dump(mode="json")  # fmt: skip


def search(query="amoeba"):
    return AIMessage(content="", tool_calls=[{"name": "search_wikimedia", "args": {"query": query}, "id": "s1"}])


def submit(*candidates, call_id="c1"):
    chosen = [
        {"source": "wikimedia", "file_url": r["file_url"], "page_url": r["page_url"], "title": r["title"],
         "license": r["license"], "attribution": r["attribution"], "why": "shows it"}
        for r in candidates
    ]  # fmt: skip
    return AIMessage(content="", tool_calls=[{"name": "submit_media", "args": {"candidates": chosen}, "id": call_id}])


@pytest.fixture
def branch(lesson_state, flow_settings):
    settings = flow_settings | {"media_sources": ["wikimedia"], "allowed_media_licenses": ["cc0", "cc-by-sa"]}
    return lesson_state | {"settings": settings, "topic": "Asexual reproduction"}


@pytest.fixture
def finder():
    return MediaFinder()


def run(finder, ctx, branch, library, spec=SPEC, feedback=None):
    ctx.media = library
    return finder.find(ctx, branch, spec, feedback)


def test_searches_submits_downloads_and_stores_a_ref(finder, ctx, branch, gateway, tmp_path):
    library = make_library(tmp_path, [result(1)])
    gateway.script("media.search", search(), submit(result(1)))

    ref = run(finder, ctx, branch, library)

    assert ref["kind"] == "image" and ref["mime_type"] == "image/png" and (ref["width"], ref["height"]) == (400, 300)
    assert (ref["source"], ref["license"], ref["attribution"]) == ("wikimedia", "cc-by-sa", "Jane Doe")
    assert ref["source_url"] == result(1)["page_url"] and ref["alt_text"] == "Amoeba 1" and ref["verified"] is False
    assert (tmp_path / ref["file"]).read_bytes() == png() and "_b64" not in ref
    assert library.source.queries == ["amoeba"]


def test_the_agent_is_given_the_spec_and_the_tool_names(finder, ctx, branch, gateway, tmp_path):
    library = make_library(tmp_path, [result(1)])
    gateway.script("media.search", search(), submit(result(1)))

    run(finder, ctx, branch, library)

    call = gateway.called("media.search")[0]
    assert "search_wikimedia" in call.messages[0].content and "amoeba binary fission" in call.messages[1].content
    assert [t.name for t in call.tools] == ["search_wikimedia", "submit_media"]


def test_a_vision_check_that_approves_sets_alt_text_and_caption(
    finder, ctx, branch, gateway, tmp_path, make_snapshot_for_nodes
):
    branch = branch | {"snapshot": make_snapshot_for_nodes(disabled=())}
    gateway.script("media.search", search(), submit(result(1)))
    gateway.script(
        "media.verify", {"approved": True, "reason": "clear", "alt_text": "An amoeba splitting", "caption": "Fission"}
    )

    ref = run(finder, ctx, branch, make_library(tmp_path, [result(1)]))

    assert (ref["alt_text"], ref["caption"], ref["verified"]) == ("An amoeba splitting", "Fission", True)
    image = gateway.called("media.verify")[0].messages[0].content[1]
    assert image["mime_type"] == "image/png" and image["base64"]


def test_a_rejected_picture_is_removed_and_the_agent_searches_again(
    finder, ctx, branch, gateway, tmp_path, make_snapshot_for_nodes
):
    branch = branch | {"snapshot": make_snapshot_for_nodes(disabled=())}
    library = make_library(tmp_path, [result(1), result(2)])
    gateway.script("media.search", search(), submit(result(1)), submit(result(2)))
    gateway.script(
        "media.verify",
        {"approved": False, "reason": "it is a cartoon", "alt_text": "", "caption": ""},
        {"approved": True, "reason": "ok", "alt_text": "alt", "caption": "cap"},
    )

    ref = run(finder, ctx, branch, library)

    assert ref["title"] == "Amoeba 2"
    assert len(list(tmp_path.rglob("*.png"))) == 1  # the rejected file was discarded
    second_round = gateway.called("media.search")[2].messages
    assert any("rejected: Amoeba 1: it is a cartoon" in str(m.content) for m in second_round)


def test_a_picture_the_vision_models_could_not_judge_is_kept_unverified(
    finder, ctx, branch, gateway, tmp_path, make_snapshot_for_nodes, events
):
    branch = branch | {"snapshot": make_snapshot_for_nodes(disabled=())}
    gateway.script("media.search", search(), submit(result(1)))
    gateway.scripts["media.verify"] = [AllModelsFailed("media.verify", ["gemini: 503"])]

    ref = run(finder, ctx, branch, make_library(tmp_path, [result(1)]))

    assert ref["title"] == "Amoeba 1" and ref["verified"] is False
    assert len(list(tmp_path.rglob("*.png"))) == 1  # the file was kept
    assert "could not be checked by the vision model" in events.of_type("warning")[0]["message"]


def test_the_vision_check_is_skipped_when_the_node_has_no_model(finder, ctx, branch, gateway, tmp_path):
    gateway.script("media.search", search(), submit(result(1)))

    ref = run(finder, ctx, branch, make_library(tmp_path, [result(1)]))

    assert ref["verified"] is False and gateway.called("media.verify") == []


def test_a_url_no_tool_returned_is_reported_back_and_the_agent_tries_again(finder, ctx, branch, gateway, tmp_path):
    library = make_library(tmp_path, [result(1)])
    invented = {**result(9), "file_url": "https://evil.example.org/x.png"}
    gateway.script("media.search", search(), submit(invented), submit(result(1)))

    ref = run(finder, ctx, branch, library)

    assert ref["title"] == "Amoeba 1"
    retry_prompt = gateway.called("media.search")[2].messages
    assert any("not returned by a search tool" in str(m.content) for m in retry_prompt)


def test_gives_up_when_every_round_finds_nothing_usable(finder, ctx, branch, gateway, tmp_path):
    library = make_library(tmp_path, [result(1)], body=b"<html>not an image</html>")
    gateway.script("media.search", search(), submit(result(1)), submit(result(1)))

    assert run(finder, ctx, branch, library) is None
    assert list(tmp_path.rglob("*.png")) == []


def test_gives_up_when_the_agent_keeps_searching_past_the_tool_step_cap(finder, ctx, branch, gateway, tmp_path):
    library = make_library(tmp_path, [result(1)])
    gateway.script("media.search", *[search(f"try {n}") for n in range(20)])

    assert run(finder, ctx, branch, library) is None
    assert len(gateway.called("media.search")) == 6  # NodeConfig.max_tool_steps


def test_an_agent_that_answers_in_prose_is_nudged_to_use_the_tools(finder, ctx, branch, gateway, tmp_path):
    library = make_library(tmp_path, [result(1)])
    prose = AIMessage(content="I think an amoeba picture would be nice.")
    gateway.script("media.search", prose, search(), submit(result(1)))

    ref = run(finder, ctx, branch, library)

    assert ref is not None
    assert "submit_media" in str(gateway.called("media.search")[1].messages[-1].content)


def test_a_search_that_raises_is_reported_to_the_agent_not_a_crash(finder, ctx, branch, gateway, tmp_path):
    library = make_library(tmp_path, MediaError("wikimedia search failed: ConnectError"), [result(1)])
    gateway.script("media.search", search(), search("again"), submit(result(1)))

    ref = run(finder, ctx, branch, library)

    assert ref is not None
    tool_reply = gateway.called("media.search")[1].messages[-1]
    assert "Search failed: MediaError" in tool_reply.content


def test_invalid_submit_arguments_are_reported_back(finder, ctx, branch, gateway, tmp_path):
    bad = AIMessage(
        content="", tool_calls=[{"name": "submit_media", "args": {"candidates": [{"file_url": "x"}]}, "id": "c0"}]
    )
    library = make_library(tmp_path, [result(1)])
    gateway.script("media.search", search(), bad, submit(result(1)))

    ref = run(finder, ctx, branch, library)

    assert ref is not None
    assert any("arguments were invalid" in str(m.content) for m in gateway.called("media.search")[2].messages)


def test_an_empty_submission_means_nothing_suitable(finder, ctx, branch, gateway, tmp_path):
    gateway.script("media.search", submit(), submit())

    assert run(finder, ctx, branch, make_library(tmp_path, [])) is None


def test_every_spec_starts_a_fresh_session(finder, ctx, branch, gateway, tmp_path):
    library = make_library(tmp_path, [result(1)])
    gateway.script("media.search", search(), submit(result(1)), search(), submit(result(1)))

    first = run(finder, ctx, branch, library)
    second = run(finder, ctx, branch, library, spec=SPEC | {"id": "second"})

    assert first["asset_id"] != second["asset_id"] and second["spec_id"] == "second"


def test_the_agents_licences_come_from_the_lessons_settings(finder, ctx, branch, gateway, tmp_path):
    seen = {}

    class Spy(type(make_library(tmp_path, []).sources["wikimedia"])):
        def search(self, session, query, media_type="image"):
            seen["licenses"] = session.allowed_licenses
            return super().search(session, query, media_type)

    library = make_library(tmp_path, [result(1)])
    library.sources["wikimedia"] = spy = Spy([result(1)])
    gateway.script("media.search", search(), submit(result(1)))

    run(finder, ctx, branch, library)

    assert seen["licenses"] == {"cc0", "cc-by-sa"} and spy.queries == ["amoeba"]


def test_the_graph_builder_compiles_without_a_checkpointer():
    assert MediaGraphBuilder().build() is not None
    assert json.dumps({"ok": True})  # (keeps the json import honest for the tools' JSON replies)
