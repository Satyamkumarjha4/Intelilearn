"""A guarded download. The model never supplies a URL we fetch on trust: only URLs a search tool returned in this
session, over https, never to a private or loopback address, with the type sniffed from the bytes and size limits."""

import io
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from PIL import Image

from .errors import MediaError
from .session import MediaSession

MAX_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 4096 * 4096
MIN_SIDE = 200
MAX_REDIRECTS = 4
MAGIC = [
    (b"\x89PNG\r\n\x1a\n", "image/png", "png"),
    (b"\xff\xd8\xff", "image/jpeg", "jpg"),
    (b"GIF87a", "image/gif", "gif"),
    (b"GIF89a", "image/gif", "gif"),
]


@dataclass(frozen=True)
class Download:
    content: bytes
    mime: str
    extension: str
    width: int
    height: int


class UrlGuard:
    """Refuses a URL that is not https or that resolves to an address inside the network (SSRF)."""

    def __init__(self, resolve=socket.getaddrinfo, allow_private: bool = False):
        self.resolve, self.allow_private = resolve, allow_private

    def check(self, url: str) -> None:
        parsed = urlparse(url)
        if not parsed.hostname:
            raise MediaError(f"not a usable URL: {url}")
        if self.allow_private:  # only the offline walk-through's fake media host needs this
            return
        if parsed.scheme != "https":
            raise MediaError(f"only https URLs are downloaded: {url}")
        for info in self.resolve(parsed.hostname, 443, proto=socket.IPPROTO_TCP):
            address = ipaddress.ip_address(info[4][0])
            if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved:
                raise MediaError(f"{parsed.hostname} resolves to a private address")


class MediaDownloader:
    def __init__(self, client: httpx.Client, guard: UrlGuard | None = None):
        self.client = client
        self.guard = guard or UrlGuard()

    def download(self, session: MediaSession, url: str) -> Download:
        """Raises MediaError for anything unacceptable."""
        if url not in session.seen:
            raise MediaError("that URL was not returned by a search tool")
        content = self._fetch(url)
        mime, extension = self._sniff(content)
        width, height = self._size(content)
        return Download(content, mime, extension, width, height)

    def _fetch(self, url: str) -> bytes:
        for _ in range(MAX_REDIRECTS):  # redirects are followed by hand so every hop is checked
            self.guard.check(url)
            try:
                with self.client.stream("GET", url) as response:
                    if response.is_redirect:
                        url = str(response.next_request.url) if response.next_request else ""
                        continue
                    response.raise_for_status()
                    content = b""
                    for chunk in response.iter_bytes():
                        content += chunk
                        if len(content) > MAX_BYTES:
                            raise MediaError("file is larger than 8 MB")
                    return content
            except httpx.HTTPError as exc:
                raise MediaError(f"download failed: {type(exc).__name__}: {exc}") from exc
        raise MediaError("too many redirects")

    @staticmethod
    def _sniff(content: bytes) -> tuple[str, str]:
        for magic, mime, extension in MAGIC:
            if content.startswith(magic):
                return mime, extension
        if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
            return "image/webp", "webp"
        raise MediaError("not a PNG, JPEG, GIF or WebP image")

    @staticmethod
    def _size(content: bytes) -> tuple[int, int]:
        try:
            with Image.open(io.BytesIO(content)) as image:
                width, height = image.size
        except Exception as exc:
            raise MediaError(f"unreadable image: {exc}") from exc
        if width * height > MAX_PIXELS:
            raise MediaError("image dimensions are too large")
        if min(width, height) < MIN_SIDE:
            raise MediaError("image is too small to be useful")
        return width, height
