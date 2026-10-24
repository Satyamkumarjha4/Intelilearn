from dataclasses import dataclass, field


@dataclass
class MediaSession:
    """One media-agent run: the licences it may use and the files its tools returned (only those may be downloaded)."""

    allowed_licenses: set[str]
    seen: dict[str, dict] = field(default_factory=dict)  # file_url → search result

    def remember(self, results: list[dict], limit: int = 8) -> list[dict]:
        usable = [r for r in results if r.get("file_url")][:limit]
        for result in usable:
            self.seen[result["file_url"]] = result
        return usable
