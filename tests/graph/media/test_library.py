"""Unit under test: `graph.media.library.MediaLibrary` (the facade the media agent uses) and `MediaStorage`.

Why: the agent only ever sees the library's tools, so what they are called, what they return and which sources they
cover decides what it can find. Storage decides where files land and that a rejected one is removed.

Use cases:
- the tools are one search per enabled source plus submit_media; a disabled or unconfigured source has no tool
- a search tool returns the results as JSON, or a hint to try another query when there are none, and remembers the URLs
- a failing source raises (the node turns it into information for the agent)
- GIPHY's tool takes only a query and is named search_gifs
- default() wires the real sources from settings, with GIPHY only when it has a key
- storing writes the bytes under MEDIA_ROOT/lesson-media/<lesson>/<asset id>.<ext>; discarding removes them
"""

import json

import httpx

from graph.media import MediaLibrary, MediaSession, MediaStorage
from graph.media.downloader import MediaDownloader


class FakeSource:
    def __init__(self, key, results=(), error=None):
        self.key, self.results, self.error, self.queries = key, list(results), error, []

    def search(self, session, query, media_type="image"):
        self.queries.append((query, media_type))
        if self.error:
            raise self.error
        return session.remember(self.results)


def library(**sources):
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    return MediaLibrary(sources, MediaDownloader(client))


def test_has_one_search_tool_per_enabled_source_plus_submit_media():
    lib = library(wikimedia=FakeSource("wikimedia"), openverse=FakeSource("openverse"), giphy=FakeSource("giphy"))

    names = [t.name for t in lib.tools(MediaSession({"cc0"}), ["wikimedia", "giphy"])]

    assert names == ["search_wikimedia", "search_gifs", "submit_media"]


def test_a_source_that_is_not_configured_has_no_tool_even_when_enabled():
    lib = library(wikimedia=FakeSource("wikimedia"))

    names = [t.name for t in lib.tools(MediaSession({"cc0"}), ["wikimedia", "openverse", "giphy"])]

    assert names == ["search_wikimedia", "submit_media"]


def test_a_search_tool_returns_json_and_remembers_the_urls():
    result = {"source": "wikimedia", "file_url": "https://a/1.png", "title": "T"}
    source = FakeSource("wikimedia", [result])
    session = MediaSession({"cc0"})
    tool = {t.name: t for t in library(wikimedia=source).tools(session, ["wikimedia"])}["search_wikimedia"]

    reply = tool.invoke({"query": "amoeba", "media_type": "gif"})

    assert json.loads(reply) == [result]
    assert source.queries == [("amoeba", "gif")] and "https://a/1.png" in session.seen


def test_no_results_is_a_hint_not_an_empty_string():
    tool = library(wikimedia=FakeSource("wikimedia")).tools(MediaSession(set()), ["wikimedia"])[0]

    assert "try another query" in tool.invoke({"query": "x"})


def test_a_failing_source_raises_so_the_node_can_report_it_to_the_agent():
    from graph.media import MediaError

    tool = library(wikimedia=FakeSource("wikimedia", error=MediaError("down"))).tools(
        MediaSession(set()), ["wikimedia"]
    )[0]

    try:
        tool.invoke({"query": "x"})
    except MediaError as exc:
        assert "down" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected a MediaError")


def test_the_gif_tool_takes_only_a_query():
    tool = {t.name: t for t in library(giphy=FakeSource("giphy")).tools(MediaSession({"giphy"}), ["giphy"])}[
        "search_gifs"
    ]

    assert set(tool.args) == {"query"}


def test_default_wires_the_real_sources_and_giphy_only_with_a_key(settings):
    settings.GIPHY_API_KEY = ""
    without = MediaLibrary.default()
    settings.GIPHY_API_KEY = "k"
    with_key = MediaLibrary.default()

    assert set(without.sources) == {"wikimedia", "openverse"}
    assert set(with_key.sources) == {"wikimedia", "openverse", "giphy"}
    assert without.sources["wikimedia"].url == settings.WIKIMEDIA_API_URL


def test_storing_writes_under_the_lessons_folder_and_discarding_removes_the_file(tmp_path):
    storage = MediaStorage(tmp_path)

    stored = storage.store("lesson-1", b"bytes", "png")

    assert stored.relative == f"lesson-media/lesson-1/{stored.asset_id}.png"
    assert (tmp_path / stored.relative).read_bytes() == b"bytes"
    storage.discard(stored.relative)
    storage.discard(stored.relative)
    assert not (tmp_path / stored.relative).exists()


def test_storage_defaults_to_media_root(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path

    stored = MediaStorage().store("l", b"x", "gif")

    assert (tmp_path / stored.relative).exists()
