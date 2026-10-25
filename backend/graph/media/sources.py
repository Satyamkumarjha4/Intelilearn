"""Where openly licensed media is searched: one `MediaSource` per service, each mapping its API to one result shape.

A source returns `[]` when nothing matches (never `None`) and raises `MediaError` when the service cannot be reached,
so the agent can tell "no results" from "try again later".
"""

import html
import re
from typing import Protocol

import httpx

from .errors import MediaError
from .licenses import LicensePolicy
from .session import MediaSession


def strip_html(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


class MediaSource(Protocol):
    key: str

    def search(self, session: MediaSession, query: str, media_type: str = "image") -> list[dict]: ...


class HttpMediaSource:
    key: str

    def __init__(self, client: httpx.Client, url: str):
        self.client, self.url = client, url

    def get(self, params: dict) -> dict:
        try:
            response = self.client.get(self.url, params=params)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise MediaError(f"{self.key} search failed: {type(exc).__name__}: {exc}") from exc


class WikimediaSource(HttpMediaSource):
    key = "wikimedia"

    def search(self, session: MediaSession, query: str, media_type: str = "image") -> list[dict]:
        filters = "filemime:image/gif" if media_type == "gif" else "filetype:bitmap"
        data = self.get(
            {
                "action": "query",
                "format": "json",
                "generator": "search",
                "gsrnamespace": 6,
                "gsrlimit": 12,
                "gsrsearch": f"{query} {filters}",
                "prop": "imageinfo",
                "iiprop": "url|extmetadata|mime|size",
                "iiurlwidth": 1200,
            }  # fmt: skip
        )
        results = []
        for page in ((data.get("query") or {}).get("pages") or {}).values():
            info = (page.get("imageinfo") or [{}])[0]
            meta = info.get("extmetadata") or {}
            license_ = LicensePolicy.normalise((meta.get("LicenseShortName") or {}).get("value", ""))
            if license_ not in session.allowed_licenses:
                continue
            results.append(
                {
                    "source": self.key,
                    "file_url": info.get("thumburl") or info.get("url"),
                    "page_url": info.get("descriptionurl", ""),
                    "title": page.get("title", "").removeprefix("File:"),
                    "license": license_,
                    "attribution": strip_html((meta.get("Artist") or {}).get("value", "")) or "Wikimedia Commons",
                    "description": strip_html((meta.get("ImageDescription") or {}).get("value", ""))[:300],
                    "width": info.get("thumbwidth") or info.get("width"),
                    "height": info.get("thumbheight") or info.get("height"),
                }
            )
        return session.remember(results)


class OpenverseSource(HttpMediaSource):
    key = "openverse"
    API_LICENSES = {"cc0": "cc0", "pdm": "pdm", "cc-by": "by", "cc-by-sa": "by-sa"}

    def search(self, session: MediaSession, query: str, media_type: str = "image") -> list[dict]:
        wanted = [self.API_LICENSES[name] for name in sorted(session.allowed_licenses) if name in self.API_LICENSES]
        data = self.get(
            {
                "q": query,
                "page_size": 12,
                "mature": "false",
                "license": ",".join(wanted) or "cc0",
                "extension": "gif" if media_type == "gif" else "jpg,png",
            }  # fmt: skip
        )
        results = []
        for item in data.get("results", []):
            license_ = LicensePolicy.normalise(item.get("license", ""))
            if license_ not in session.allowed_licenses:
                continue
            results.append(
                {
                    "source": self.key,
                    "file_url": item.get("url"),
                    "page_url": item.get("foreign_landing_url") or "",
                    "title": item.get("title") or "",
                    "license": license_,
                    "attribution": item.get("attribution") or item.get("creator") or "Openverse",
                    "description": ", ".join(t.get("name", "") for t in (item.get("tags") or [])[:8]),
                    "width": item.get("width"),
                    "height": item.get("height"),
                }
            )
        return session.remember(results)


class GiphySource(HttpMediaSource):
    """GIFs, when `giphy` is an allowed source and there is an API key. GIPHY content is not openly licensed, so it
    is only used when the operator opts in by listing `giphy` among the allowed licences."""

    key = "giphy"

    def __init__(self, client: httpx.Client, url: str, api_key: str):
        super().__init__(client, url)
        self.api_key = api_key

    def search(self, session: MediaSession, query: str, media_type: str = "gif") -> list[dict]:
        if not self.api_key or "giphy" not in session.allowed_licenses:
            return []
        data = self.get({"api_key": self.api_key, "q": query, "limit": 10, "rating": "g"})
        results = []
        for item in data.get("data", []):
            image = (item.get("images") or {}).get("downsized_medium") or {}
            results.append(
                {
                    "source": self.key,
                    "file_url": image.get("url"),
                    "page_url": item.get("url", ""),
                    "title": item.get("title", ""),
                    "license": "giphy",
                    "attribution": f"GIPHY / {item.get('username') or 'unknown'}",
                    "description": "",
                    "width": image.get("width"),
                    "height": image.get("height"),
                }
            )
        return session.remember(results)
