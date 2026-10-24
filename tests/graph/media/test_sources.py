"""Unit under test: the media sources in `graph.media.sources` (`WikimediaSource`, `OpenverseSource`, `GiphySource`) and
`MediaSession`, against recorded API replies served by `httpx.MockTransport`.

Why: they are the only place we talk to the media services. A source that mis-maps a field shows the wrong attribution
under a picture; one that lets a disallowed licence through puts unlicensed media in a lesson; one that raises a bare
httpx error or returns `None` for "no results" breaks the agent's loop.

Use cases:
- Wikimedia replies are mapped to results with the thumbnail URL, plain-text attribution and description, and the
  normalised licence; results whose licence is not allowed are dropped
- Wikimedia asks for GIFs or bitmaps as requested
- Openverse replies are mapped, filtered by licence, and the allowed licences are sent as its filter
- GIPHY results are mapped, and GIPHY is silent without a key or without being an allowed licence
- no results is an empty list, never None
- a transport failure, an error status or a body that is not JSON is a MediaError naming the source
- a session remembers the URLs it returned (and no more than the limit), and drops results without a URL
"""

import httpx
import pytest

from graph.media import GiphySource, MediaError, MediaSession, OpenverseSource, WikimediaSource

ALLOWED = {"cc0", "pdm", "cc-by", "cc-by-sa"}


def client_for(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def json_reply(body, status=200):
    return lambda request: httpx.Response(status, json=body)


WIKIMEDIA_BODY = {
    "query": {
        "pages": {
            "1": {
                "title": "File:Amoeba proteus.jpg",
                "imageinfo": [
                    {
                        "url": "https://upload.example.org/full.jpg",
                        "thumburl": "https://upload.example.org/thumb.jpg",
                        "descriptionurl": "https://commons.example.org/File:Amoeba_proteus.jpg",
                        "thumbwidth": 1200,
                        "thumbheight": 900,
                        "extmetadata": {
                            "LicenseShortName": {"value": "CC BY-SA 4.0"},
                            "Artist": {"value": '<a href="x">Jane &amp; Co</a>'},
                            "ImageDescription": {"value": "An <b>amoeba</b> under the microscope"},
                        },
                    }
                ],
            },
            "2": {
                "title": "File:Nope.jpg",
                "imageinfo": [{"url": "https://upload.example.org/nope.jpg",
                               "extmetadata": {"LicenseShortName": {"value": "CC BY-NC 4.0"}}}],
            },
        }
    }
}  # fmt: skip


class TestWikimedia:
    def test_maps_a_reply_and_drops_licences_that_are_not_allowed(self):
        session = MediaSession(ALLOWED)

        results = WikimediaSource(client_for(json_reply(WIKIMEDIA_BODY)), "https://wiki.test/api").search(
            session, "amoeba"
        )

        assert results == [
            {
                "source": "wikimedia",
                "file_url": "https://upload.example.org/thumb.jpg",
                "page_url": "https://commons.example.org/File:Amoeba_proteus.jpg",
                "title": "Amoeba proteus.jpg",
                "license": "cc-by-sa",
                "attribution": "Jane & Co",
                "description": "An amoeba under the microscope",
                "width": 1200,
                "height": 900,
            }
        ]

    def test_asks_for_bitmaps_or_gifs_as_requested(self):
        seen = []

        def handler(request):
            seen.append(request.url.params["gsrsearch"])
            return httpx.Response(200, json={})

        source = WikimediaSource(client_for(handler), "https://wiki.test/api")
        source.search(MediaSession(ALLOWED), "cell division")
        source.search(MediaSession(ALLOWED), "cell division", "gif")

        assert seen == ["cell division filetype:bitmap", "cell division filemime:image/gif"]

    def test_no_results_is_an_empty_list(self):
        source = WikimediaSource(client_for(json_reply({"query": {}})), "https://wiki.test/api")

        assert source.search(MediaSession(ALLOWED), "nothing") == []


OPENVERSE_BODY = {
    "results": [
        {"url": "https://img.example.org/a.jpg", "foreign_landing_url": "https://example.org/a", "title": "Cell",
         "license": "by", "attribution": '"Cell" by Ann is licensed under CC BY 2.0', "width": 800, "height": 600,
         "tags": [{"name": "cell"}, {"name": "biology"}]},
        {"url": "https://img.example.org/b.jpg", "title": "Nc", "license": "by-nc"},
    ]
}  # fmt: skip


class TestOpenverse:
    def test_maps_results_and_filters_by_licence(self):
        results = OpenverseSource(client_for(json_reply(OPENVERSE_BODY)), "https://ov.test/v1/images/").search(
            MediaSession(ALLOWED), "cell"
        )

        assert [r["file_url"] for r in results] == ["https://img.example.org/a.jpg"]
        assert results[0]["license"] == "cc-by" and results[0]["description"] == "cell, biology"
        assert results[0]["attribution"].startswith('"Cell" by Ann')

    def test_sends_the_allowed_licences_and_the_file_types_as_its_filter(self):
        seen = []

        def handler(request):
            seen.append(dict(request.url.params))
            return httpx.Response(200, json={"results": []})

        source = OpenverseSource(client_for(handler), "https://ov.test/v1/images/")
        source.search(MediaSession({"cc0", "cc-by-sa", "gfdl"}), "cell")
        source.search(MediaSession({"cc0"}), "cell", "gif")

        assert seen[0]["license"] == "by-sa,cc0" and seen[0]["extension"] == "jpg,png"
        assert seen[1]["license"] == "cc0" and seen[1]["extension"] == "gif"

    def test_with_no_known_licence_it_still_asks_only_for_cc0(self):
        seen = []

        def handler(request):
            seen.append(request.url.params["license"])
            return httpx.Response(200, json={"results": []})

        OpenverseSource(client_for(handler), "https://ov.test/").search(MediaSession(set()), "x")

        assert seen == ["cc0"]


GIPHY_BODY = {"data": [{"url": "https://giphy.test/g1", "title": "Splitting", "username": "bio",
                        "images": {"downsized_medium": {"url": "https://media.giphy.test/g1.gif", "width": "400",
                                                        "height": "300"}}}]}  # fmt: skip


class TestGiphy:
    def test_maps_results_when_allowed_and_keyed(self):
        results = GiphySource(client_for(json_reply(GIPHY_BODY)), "https://giphy.test/search", "key").search(
            MediaSession({"giphy"}), "cell division"
        )

        assert results[0]["file_url"] == "https://media.giphy.test/g1.gif"
        assert (results[0]["license"], results[0]["attribution"]) == ("giphy", "GIPHY / bio")

    def test_is_silent_without_a_key_or_without_being_allowed(self):
        def boom(request):
            raise AssertionError("must not be called")

        assert GiphySource(client_for(boom), "https://giphy.test/", "").search(MediaSession({"giphy"}), "x") == []
        assert GiphySource(client_for(boom), "https://giphy.test/", "k").search(MediaSession({"cc0"}), "x") == []


@pytest.mark.parametrize("source_class", [WikimediaSource, OpenverseSource])
class TestFailures:
    def test_a_transport_failure_is_a_media_error_naming_the_source(self, source_class):
        def handler(request):
            raise httpx.ConnectError("refused")

        with pytest.raises(MediaError, match=f"{source_class.key} search failed: ConnectError"):
            source_class(client_for(handler), "https://x.test/").search(MediaSession(ALLOWED), "q")

    def test_an_error_status_is_a_media_error(self, source_class):
        with pytest.raises(MediaError, match="429"):
            source_class(client_for(json_reply({}, 429)), "https://x.test/").search(MediaSession(ALLOWED), "q")

    def test_a_body_that_is_not_json_is_a_media_error(self, source_class):
        with pytest.raises(MediaError, match="search failed"):
            source_class(client_for(lambda r: httpx.Response(200, text="<html>")), "https://x.test/").search(
                MediaSession(ALLOWED), "q"
            )


class TestSession:
    def test_remembers_the_urls_returned_and_drops_results_without_one(self):
        session = MediaSession(ALLOWED)

        kept = session.remember([{"file_url": "https://a/1"}, {"file_url": None}, {"title": "no url"}])

        assert kept == [{"file_url": "https://a/1"}] and set(session.seen) == {"https://a/1"}

    def test_returns_at_most_the_limit(self):
        session = MediaSession(ALLOWED)

        kept = session.remember([{"file_url": f"https://a/{n}"} for n in range(20)], limit=8)

        assert len(kept) == 8 and len(session.seen) == 8
