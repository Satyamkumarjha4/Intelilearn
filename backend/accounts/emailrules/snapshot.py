"""Refreshing the vendored list of disposable domains (plan D8, U7): fetch, filter, write with a header.

`DisposableSnapshot` fetches the public blocklist and the commit that last changed it, **drops every major real mail
provider** (a mistaken upstream line must never stop a Gmail or a Sify user signing up), refuses a list that is
implausibly small, and writes the file with a header that names its source, commit and date. The HTTP client is
injected, so the tests run it against a `httpx.MockTransport`."""

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx

from .disposable import DisposableDomains
from .providers import MajorProviders


class SnapshotRefused(Exception):
    """The fetched list cannot be used; the file on disk is left as it was."""


@dataclass(frozen=True)
class SnapshotResult:
    path: Path
    domains: int
    commit: str
    removed: tuple[str, ...]  # real providers the upstream list held, which were dropped


class DisposableSnapshot:
    REPO = "disposable-email-domains/disposable-email-domains"
    FILE = "disposable_email_blocklist.conf"
    LIST_URL = f"https://raw.githubusercontent.com/{REPO}/main/{FILE}"
    COMMIT_URL = f"https://api.github.com/repos/{REPO}/commits?path={FILE}&per_page=1"
    MINIMUM = 1000  # the real list has about ten thousand; far fewer means the fetch went wrong

    def __init__(self, client: httpx.Client, path: Path | None = None, today: date | None = None):
        self.client, self.path, self.today = client, path or DisposableDomains.BLOCKLIST, today or date.today()

    def refresh(self) -> SnapshotResult:
        text = self._get(self.LIST_URL)
        commit, committed = self._commit()
        names = {line.strip().lower() for line in text.splitlines() if line.strip() and not line.startswith("#")}
        names = {name for name in names if "." in name}  # a bare suffix such as `com` must never be a blocked name
        removed = tuple(sorted(names & MajorProviders.DOMAINS))
        kept = sorted(names - MajorProviders.DOMAINS)
        if len(kept) < self.MINIMUM:
            raise SnapshotRefused(f"The list has {len(kept)} domains; fewer than {self.MINIMUM} cannot be right.")
        self.path.write_text(self._header(commit, committed, removed) + "\n".join(kept) + "\n", encoding="utf-8")
        return SnapshotResult(self.path, len(kept), commit, removed)

    def _header(self, commit: str, committed: str, removed: tuple[str, ...]) -> str:
        lines = [
            "# Disposable email domains, vendored from the public blocklist (CC0). Do not edit by hand:",
            "# run `manage.py refresh_disposable_domains`. The allow-list (school_allowlist.txt) always wins.",
            f"# Source: https://github.com/{self.REPO}/blob/main/{self.FILE}",
            f"# Source commit: {commit} ({committed})",
            f"# Fetched: {self.today.isoformat()}",
            f"# Dropped, real mail providers that must never be blocked: {', '.join(removed) or 'none'}",
        ]
        return "\n".join(lines) + "\n"

    def _get(self, url: str) -> str:
        try:
            response = self.client.get(url)
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise SnapshotRefused(f"Could not fetch {url}: {type(error).__name__}") from error
        return response.text

    def _commit(self) -> tuple[str, str]:
        try:
            latest = self.client.get(self.COMMIT_URL).raise_for_status().json()[0]
            return latest["sha"], latest["commit"]["committer"]["date"][:10]
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as error:
            raise SnapshotRefused(f"Could not read the source commit: {type(error).__name__}") from error
