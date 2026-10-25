"""One object for finding, downloading and storing media (Facade): the media agent's tools and its guarded download."""

import json

import httpx
from django.conf import settings
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from ..schemas.interactive import MediaSelection
from .downloader import Download, MediaDownloader, UrlGuard
from .session import MediaSession
from .sources import GiphySource, MediaSource, OpenverseSource, WikimediaSource
from .storage import MediaStorage, StoredFile

USER_AGENT = "LessonCrafter/0.1 (local educational app)"


class SearchArgs(BaseModel):
    query: str = Field(description="2-5 plain English words, e.g. 'amoeba binary fission'.")
    media_type: str = Field(default="image", description='"image" or "gif".')


class GifArgs(BaseModel):
    query: str = Field(description="2-5 plain English words.")


class MediaLibrary:
    DESCRIPTIONS = {
        "wikimedia": "Search Wikimedia Commons for openly licensed photos, diagrams, micrographs and GIFs.",
        "openverse": "Search Openverse (many open collections) for openly licensed images and GIFs.",
        "giphy": "Search GIPHY for short animated GIFs.",
    }

    def __init__(
        self,
        sources: dict[str, MediaSource],
        downloader: MediaDownloader,
        storage: MediaStorage | None = None,
    ):
        self.sources, self.downloader, self.storage = sources, downloader, storage or MediaStorage()

    @classmethod
    def default(cls, client: httpx.Client | None = None) -> "MediaLibrary":
        """The real sources (their URLs and the optional GIPHY key come from settings)."""
        client = client or httpx.Client(timeout=15, follow_redirects=False, headers={"User-Agent": USER_AGENT})
        sources: dict[str, MediaSource] = {
            "wikimedia": WikimediaSource(client, settings.WIKIMEDIA_API_URL),
            "openverse": OpenverseSource(client, settings.OPENVERSE_API_URL),
        }
        if settings.GIPHY_API_KEY:
            sources["giphy"] = GiphySource(client, settings.GIPHY_API_URL, settings.GIPHY_API_KEY)
        guard = UrlGuard(allow_private=settings.MEDIA_ALLOW_PRIVATE_HOSTS)
        return cls(sources, MediaDownloader(client, guard))

    def tools(self, session: MediaSession, enabled: list[str]) -> list[StructuredTool]:
        """The agent's tools for this session, plus the final submit_media (never executed: it ends the loop)."""
        tools = [self._search_tool(key, source, session) for key, source in self.sources.items() if key in enabled]
        tools.append(
            StructuredTool.from_function(
                lambda **kwargs: "submitted",
                name="submit_media",
                args_schema=MediaSelection,
                description="Finish: submit the best 1-3 candidates (best first), or an empty list if nothing fits.",
            )
        )
        return tools

    def _search_tool(self, key: str, source: MediaSource, session: MediaSession) -> StructuredTool:
        def run(query: str, media_type: str = "image") -> str:
            results = source.search(session, query, media_type)
            return (
                json.dumps(results, ensure_ascii=False) if results else "No openly licensed results; try another query."
            )

        return StructuredTool.from_function(
            run,
            name="search_gifs" if key == "giphy" else f"search_{key}",
            args_schema=GifArgs if key == "giphy" else SearchArgs,
            description=self.DESCRIPTIONS[key],
        )

    def download(self, session: MediaSession, url: str) -> Download:
        return self.downloader.download(session, url)

    def store(self, lesson_id: str, content: bytes, extension: str) -> StoredFile:
        return self.storage.store(lesson_id, content, extension)

    def discard(self, relative: str) -> None:
        self.storage.discard(relative)
