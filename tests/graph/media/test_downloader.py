"""Unit under test: `graph.media.downloader.MediaDownloader` and `UrlGuard`: the guarded download of a media file.

Why: the URL comes out of a language model's tool call, and the file ends up in front of a learner. Without these
guards a model could make the server fetch an internal address (SSRF), a huge file, or something that is not an image
at all, and a bad redirect could walk past the address check.

Use cases:
- a PNG, JPEG, GIF and WebP are accepted, with their type and size read from the bytes (not the URL or header)
- a URL the search tools did not return in this session is refused
- plain http, a missing host and a host that resolves to a private, loopback or link-local address are refused
- redirects are followed by hand and every hop is checked, up to a limit
- a file over 8 MB, a non-image, a corrupt image, a huge image and a tiny one are refused
- an error status or a network failure is a MediaError
- with the private-host switch on (the offline walk-through's fake host) http and private addresses are allowed
"""

import io
import socket

import httpx
import pytest
from PIL import Image

from graph.media import MediaDownloader, MediaError, MediaSession, UrlGuard

URL = "https://img.example.org/a.png"


def image_bytes(fmt="PNG", size=(300, 240)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(buffer, fmt)
    return buffer.getvalue()


def public(host, port, proto=None):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]


def downloader(handler, resolve=public, allow_private=False) -> MediaDownloader:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return MediaDownloader(client, UrlGuard(resolve=resolve, allow_private=allow_private))


def session_with(*urls) -> MediaSession:
    session = MediaSession({"cc0"})
    session.seen.update({u: {"file_url": u} for u in urls})
    return session


@pytest.mark.parametrize(
    ("fmt", "mime", "extension"),
    [
        ("PNG", "image/png", "png"),
        ("JPEG", "image/jpeg", "jpg"),
        ("GIF", "image/gif", "gif"),
        ("WEBP", "image/webp", "webp"),
    ],
)
def test_accepts_the_supported_types_reading_type_and_size_from_the_bytes(fmt, mime, extension):
    body = image_bytes(fmt)

    result = downloader(lambda r: httpx.Response(200, content=body, headers={"content-type": "text/plain"})).download(
        session_with(URL), URL
    )

    assert (result.mime, result.extension, result.width, result.height) == (mime, extension, 300, 240)
    assert result.content == body


def test_refuses_a_url_the_search_tools_did_not_return():
    with pytest.raises(MediaError, match="not returned by a search tool"):
        downloader(lambda r: httpx.Response(200, content=image_bytes())).download(session_with(), URL)


@pytest.mark.parametrize(
    ("url", "message"),
    [
        ("http://img.example.org/a.png", "only https"),
        ("ftp://img.example.org/a.png", "only https"),
        ("https:///a.png", "not a usable URL"),
    ],
)
def test_refuses_plain_http_other_schemes_and_a_missing_host(url, message):
    with pytest.raises(MediaError, match=message):
        downloader(lambda r: httpx.Response(200, content=image_bytes())).download(session_with(url), url)


@pytest.mark.parametrize("address", ["10.0.0.5", "127.0.0.1", "169.254.169.254", "192.168.1.1", "::1", "0.0.0.0"])
def test_refuses_a_host_that_resolves_inside_the_network(address):
    def private(host, port, proto=None):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]

    with pytest.raises(MediaError, match="private address"):
        downloader(lambda r: httpx.Response(200, content=image_bytes()), resolve=private).download(
            session_with(URL), URL
        )


def test_follows_redirects_by_hand_and_checks_every_hop():
    hops = []

    def resolve(host, port, proto=None):
        hops.append(host)
        return public(host, port)

    def handler(request):
        if request.url.host == "img.example.org":
            return httpx.Response(302, headers={"location": "https://cdn.example.org/b.png"})
        return httpx.Response(200, content=image_bytes())

    result = downloader(handler, resolve=resolve).download(session_with(URL), URL)

    assert hops == ["img.example.org", "cdn.example.org"] and result.width == 300


def test_a_redirect_to_a_private_address_is_refused():
    def resolve(host, port, proto=None):
        address = "10.0.0.1" if host == "internal.example.org" else "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]

    def handler(request):
        return httpx.Response(302, headers={"location": "https://internal.example.org/secret.png"})

    with pytest.raises(MediaError, match="private address"):
        downloader(handler, resolve=resolve).download(session_with(URL), URL)


def test_gives_up_after_too_many_redirects():
    def handler(request):
        return httpx.Response(302, headers={"location": URL})

    with pytest.raises(MediaError, match="too many redirects"):
        downloader(handler).download(session_with(URL), URL)


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (b"x" * (8 * 1024 * 1024 + 10), "larger than 8 MB"),
        (b"<html>not an image</html>", "not a PNG, JPEG, GIF or WebP"),
        (b"\x89PNG\r\n\x1a\n" + b"corrupt", "unreadable image"),
        (image_bytes(size=(150, 900)), "too small"),
        (image_bytes(size=(5000, 4000)), "dimensions are too large"),
    ],
    ids=["too-big", "not-an-image", "corrupt", "tiny", "huge"],
)
def test_refuses_files_that_are_not_usable_images(body, message):
    with pytest.raises(MediaError, match=message):
        downloader(lambda r: httpx.Response(200, content=body)).download(session_with(URL), URL)


def test_an_error_status_or_a_network_failure_is_a_media_error():
    with pytest.raises(MediaError, match="404"):
        downloader(lambda r: httpx.Response(404)).download(session_with(URL), URL)

    def refuse(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(MediaError, match="ConnectError"):
        downloader(refuse).download(session_with(URL), URL)


def test_the_private_host_switch_allows_http_and_private_addresses():
    url = "http://fake-media.lan:9000/a.png"

    result = downloader(lambda r: httpx.Response(200, content=image_bytes()), allow_private=True).download(
        session_with(url), url
    )

    assert result.mime == "image/png"
