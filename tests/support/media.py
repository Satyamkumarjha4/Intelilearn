"""A real `MediaLibrary` over fake sources and a mock HTTP transport, for tests of the media agent and the graph.

`make_library(tmp_path, results=…)` returns a library whose "wikimedia" source answers every search with `results`,
whose downloader serves a real PNG for any URL, and which stores files under `tmp_path`.
"""

import io
import socket

import httpx
from PIL import Image

from graph.media import MediaDownloader, MediaLibrary, MediaStorage, UrlGuard


def png(size=(400, 300)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (30, 120, 200)).save(buffer, "PNG")
    return buffer.getvalue()


def result(n: int = 1, license: str = "cc-by-sa") -> dict:
    return {
        "source": "wikimedia", "file_url": f"https://upload.example.org/amoeba{n}.png",
        "page_url": f"https://commons.example.org/File:Amoeba{n}.png", "title": f"Amoeba {n}", "license": license,
        "attribution": "Jane Doe", "description": "An amoeba", "width": 400, "height": 300,
    }  # fmt: skip


class ScriptedSource:
    """A MediaSource that returns the next scripted list of results for each search (the last one repeats)."""

    key = "wikimedia"

    def __init__(self, *searches):
        self.searches = list(searches) or [[]]
        self.queries: list[str] = []

    def search(self, session, query, media_type="image"):
        self.queries.append(query)
        results = self.searches.pop(0) if len(self.searches) > 1 else self.searches[0]
        if isinstance(results, Exception):
            raise results
        return session.remember(list(results))


def make_library(tmp_path, *searches, body: bytes | None = None, status: int = 200) -> MediaLibrary:
    def handler(request):
        return httpx.Response(status, content=body if body is not None else png())

    def public(host, port, proto=None):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]

    client = httpx.Client(transport=httpx.MockTransport(handler))
    downloader = MediaDownloader(client, UrlGuard(resolve=public))
    library = MediaLibrary({"wikimedia": ScriptedSource(*searches)}, downloader, MediaStorage(tmp_path))
    library.source = library.sources["wikimedia"]
    return library
