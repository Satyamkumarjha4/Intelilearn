"""Openly licensed media for lessons: search tools for the media agent, and a guarded download.

Safety rules:
- only licences on FlowSettings.allowed_media_licenses are ever shown to the agent;
- only URLs that a search tool returned in this session are downloaded (the model can't invent one), over
  https, never to a private/loopback address, with the file type sniffed from its bytes and size limits;
- files are stored under MEDIA_ROOT and served through signed URLs: generated code never sees an external URL.
"""

import html
import io
import ipaddress
import json
import re
import socket
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import httpx
from django.conf import settings
from langchain_core.tools import StructuredTool
from PIL import Image
from pydantic import BaseModel, Field

from .schemas.interactive import MediaSelection

USER_AGENT = "LessonCrafter/0.1 (local educational app; https://github.com/)"
MAX_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 4096 * 4096
MIN_SIDE = 200
SNIFF = [
    (b"\x89PNG\r\n\x1a\n", "image/png", "png"),
    (b"\xff\xd8\xff", "image/jpeg", "jpg"),
    (b"GIF87a", "image/gif", "gif"),
    (b"GIF89a", "image/gif", "gif"),
]


class MediaError(RuntimeError):
    pass


def normalise_license(raw: str) -> str:
    """'CC BY-SA 4.0' / 'by-sa' / 'Public domain' → 'cc-by-sa' / 'pdm' / 'cc0' (versions ignored)."""
    value = (raw or "").strip().lower().replace("_", "-")
    if value in ("cc0", "cc-zero") or "cc0" in value or "cc zero" in value:
        return "cc0"
    if value in ("pdm", "pd") or "public domain" in value or value.startswith("pd-"):
        return "pdm"
    value = re.sub(r"^cc[\s-]+", "", value)
    value = re.sub(r"[\s-]*\d+(\.\d+)?.*$", "", value).replace(" ", "-")
    return f"cc-{value}" if value in ("by", "by-sa", "by-nd", "by-nc", "by-nc-sa", "by-nc-nd") else value


def _strip_html(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


class SearchArgs(BaseModel):
    query: str = Field(description="2-5 plain English words, e.g. 'amoeba binary fission'.")
    media_type: str = Field(default="image", description='"image" or "gif".')


class GifArgs(BaseModel):
    query: str = Field(description="2-5 plain English words.")


@dataclass
class MediaSession:
    """One media-agent run: which files the tools returned (only those may be downloaded)."""

    allowed_licenses: set[str]
    seen: dict[str, dict] = field(default_factory=dict)  # file_url → result


class MediaLibrary:
    def __init__(self, client: httpx.Client | None = None, giphy_key: str | None = None, resolve=None):
        self.client = client or httpx.Client(timeout=15, follow_redirects=False, headers={"User-Agent": USER_AGENT})
        self.giphy_key = giphy_key if giphy_key is not None else settings.GIPHY_API_KEY
        self.resolve = resolve or socket.getaddrinfo

    # --- searching ---------------------------------------------------------------------------------------

    def search_wikimedia(self, session: MediaSession, query: str, media_type: str = "image") -> list[dict]:
        filters = "filemime:image/gif" if media_type == "gif" else "filetype:bitmap"
        response = self.client.get(
            "https://commons.wikimedia.org/w/api.php",
            params={
                "action": "query",
                "format": "json",
                "generator": "search",
                "gsrnamespace": 6,
                "gsrlimit": 12,
                "gsrsearch": f"{query} {filters}",
                "prop": "imageinfo",
                "iiprop": "url|extmetadata|mime|size",
                "iiurlwidth": 1200,
            },  # fmt: skip
        )
        response.raise_for_status()
        results = []
        for page in (response.json().get("query") or {}).get("pages", {}).values():
            info = (page.get("imageinfo") or [{}])[0]
            meta = info.get("extmetadata") or {}
            license_ = normalise_license((meta.get("LicenseShortName") or {}).get("value", ""))
            if license_ not in session.allowed_licenses:
                continue
            results.append({
                "source": "wikimedia",
                "file_url": info.get("thumburl") or info.get("url"),
                "page_url": info.get("descriptionurl", ""),
                "title": page.get("title", "").removeprefix("File:"),
                "license": license_,
                "attribution": _strip_html((meta.get("Artist") or {}).get("value", "")) or "Wikimedia Commons",
                "description": _strip_html((meta.get("ImageDescription") or {}).get("value", ""))[:300],
                "width": info.get("thumbwidth") or info.get("width"),
                "height": info.get("thumbheight") or info.get("height"),
            })  # fmt: skip
        return self._remember(session, results)

    def search_openverse(self, session: MediaSession, query: str, media_type: str = "image") -> list[dict]:
        licences = {"cc0": "cc0", "pdm": "pdm", "cc-by": "by", "cc-by-sa": "by-sa"}
        wanted = [licences[name] for name in session.allowed_licenses if name in licences]
        params = {"q": query, "page_size": 12, "mature": "false", "license": ",".join(wanted) or "cc0"}
        params["extension"] = "gif" if media_type == "gif" else "jpg,png"
        response = self.client.get("https://api.openverse.org/v1/images/", params=params)
        response.raise_for_status()
        results = []
        for item in response.json().get("results", []):
            license_ = normalise_license(item.get("license", ""))
            if license_ not in session.allowed_licenses:
                continue
            results.append({
                "source": "openverse",
                "file_url": item.get("url"),
                "page_url": item.get("foreign_landing_url") or "",
                "title": item.get("title") or "",
                "license": license_,
                "attribution": item.get("attribution") or item.get("creator") or "Openverse",
                "description": ", ".join(t.get("name", "") for t in (item.get("tags") or [])[:8]),
                "width": item.get("width"),
                "height": item.get("height"),
            })  # fmt: skip
        return self._remember(session, results)

    def search_gifs(self, session: MediaSession, query: str) -> list[dict]:
        if not self.giphy_key or "giphy" not in session.allowed_licenses:
            return []
        response = self.client.get(
            "https://api.giphy.com/v1/gifs/search",
            params={"api_key": self.giphy_key, "q": query, "limit": 10, "rating": "g"},
        )
        response.raise_for_status()
        results = []
        for item in response.json().get("data", []):
            image = (item.get("images") or {}).get("downsized_medium") or {}
            results.append({
                "source": "giphy", "file_url": image.get("url"), "page_url": item.get("url", ""),
                "title": item.get("title", ""), "license": "giphy",
                "attribution": f"GIPHY / {item.get('username') or 'unknown'}", "description": "",
                "width": image.get("width"), "height": image.get("height"),
            })  # fmt: skip
        return self._remember(session, results)

    @staticmethod
    def _remember(session: MediaSession, results: list[dict]) -> list[dict]:
        results = [r for r in results if r.get("file_url")]
        for result in results:
            session.seen[result["file_url"]] = result
        return results[:8]

    def tools(self, session: MediaSession, sources: list[str]) -> list[StructuredTool]:
        """The agent's tools for this session, plus the final submit_media (never executed: it ends the loop)."""

        def as_text(results: list[dict]) -> str:
            return (
                json.dumps(results, ensure_ascii=False) if results else "No openly licensed results; try another query."
            )

        tools = []
        if "wikimedia" in sources:
            tools.append(StructuredTool.from_function(
                lambda query, media_type="image": as_text(self.search_wikimedia(session, query, media_type)),
                name="search_wikimedia", args_schema=SearchArgs,
                description="Search Wikimedia Commons for openly licensed photos, diagrams, micrographs and GIFs.",
            ))  # fmt: skip
        if "openverse" in sources:
            tools.append(StructuredTool.from_function(
                lambda query, media_type="image": as_text(self.search_openverse(session, query, media_type)),
                name="search_openverse", args_schema=SearchArgs,
                description="Search Openverse (many open collections) for openly licensed images and GIFs.",
            ))  # fmt: skip
        if "giphy" in sources and self.giphy_key:
            tools.append(StructuredTool.from_function(
                lambda query: as_text(self.search_gifs(session, query)),
                name="search_gifs", args_schema=GifArgs, description="Search GIPHY for short animated GIFs.",
            ))  # fmt: skip
        tools.append(StructuredTool.from_function(
            lambda **kwargs: "submitted", name="submit_media", args_schema=MediaSelection,
            description="Finish: submit the best 1-3 candidates (best first), or an empty list if nothing fits.",
        ))  # fmt: skip
        return tools

    # --- downloading ---------------------------------------------------------------------------------------

    def _check_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise MediaError(f"only https URLs are downloaded: {url}")
        for info in self.resolve(parsed.hostname, 443, proto=socket.IPPROTO_TCP):
            address = ipaddress.ip_address(info[4][0])
            if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved:
                raise MediaError(f"{parsed.hostname} resolves to a private address")

    def download(self, session: MediaSession, url: str) -> tuple[bytes, str, str, int, int]:
        """→ (content, mime, extension, width, height). Raises MediaError for anything unacceptable."""
        if url not in session.seen:
            raise MediaError("that URL was not returned by a search tool")
        for _ in range(4):  # follow a few redirects by hand, re-checking each hop
            self._check_url(url)
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
                break
        else:
            raise MediaError("too many redirects")

        mime, extension = next(((m, e) for magic, m, e in SNIFF if content.startswith(magic)), (None, None))
        if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
            mime, extension = "image/webp", "webp"
        if mime is None:
            raise MediaError("not a PNG, JPEG, GIF or WebP image")
        try:
            with Image.open(io.BytesIO(content)) as image:
                width, height = image.size
        except Exception as exc:
            raise MediaError(f"unreadable image: {exc}") from exc
        if width * height > MAX_PIXELS:
            raise MediaError("image dimensions are too large")
        if min(width, height) < MIN_SIDE:
            raise MediaError("image is too small to be useful")
        return content, mime, extension, width, height

    def store(self, lesson_id: str, content: bytes, extension: str) -> tuple[str, str]:
        """Write the file under MEDIA_ROOT → (asset id, path relative to MEDIA_ROOT)."""
        asset_id = str(uuid.uuid4())
        relative = f"lesson-media/{lesson_id}/{asset_id}.{extension}"
        path = Path(settings.MEDIA_ROOT) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return asset_id, relative

    @staticmethod
    def discard(relative: str) -> None:
        (Path(settings.MEDIA_ROOT) / relative).unlink(missing_ok=True)
