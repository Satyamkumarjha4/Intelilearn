"""Unit under test: `accounts.emailrules.snapshot.DisposableSnapshot`, which refreshes the vendored blocklist
(`manage.py refresh_disposable_domains`).

Why: the list is fetched from strangers' repository. A fetch that returns a mistaken line for Gmail, an empty file or an
error page must never end up blocking real people, and a snapshot must say where it came from. So the refresh drops
the major providers, refuses a list that cannot be right and leaves the file on disk alone when anything goes wrong.
The tests run against an `httpx.MockTransport`: nothing here touches the network.

Use cases:
- a good fetch writes the names sorted, with a header naming the source, the commit and its date, and the day fetched
- a major real provider in the upstream list is dropped and named in the header (sify.com really is on the upstream
  list)
- a bare suffix (no dot) in the list is never kept as a blocked name
- a list with fewer names than plausible is refused and the file is left as it was
- a failed fetch of the list, or of the commit, is refused with a plain reason and the file is left as it was
"""

from datetime import date

import httpx
import pytest

from accounts.emailrules.snapshot import DisposableSnapshot, SnapshotRefused

COMMIT = {"sha": "a" * 40, "commit": {"committer": {"date": "2026-11-08T18:39:02Z"}}}


def upstream(names):
    return "\n".join(names) + "\n"


def good_names(count=1200):
    return [f"throwaway{n}.example" for n in range(count)]


def client(list_text=None, commit=COMMIT, list_status=200, commit_status=200):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "raw.githubusercontent.com":
            return httpx.Response(list_status, text=list_text if list_text is not None else upstream(good_names()))
        return httpx.Response(commit_status, json=[commit])

    return httpx.Client(transport=httpx.MockTransport(handler))


def snapshot(tmp_path, **kwargs):
    path = tmp_path / "list.txt"
    path.write_text("# the old file\nold.example\n", encoding="utf-8")
    return path, DisposableSnapshot(client(**kwargs), path=path, today=date(2026, 11, 12))


def test_a_good_fetch_writes_the_sorted_names_with_a_header_naming_the_source(tmp_path):
    path, refresh = snapshot(tmp_path, list_text=upstream(["b.example", *good_names(), "a.example"]))

    result = refresh.refresh()

    text = path.read_text(encoding="utf-8")
    assert result.domains == 1202 and result.commit == "a" * 40 and result.removed == ()
    assert f"# Source commit: {'a' * 40} (2026-11-08)" in text
    assert "# Fetched: 2026-11-12" in text
    assert "disposable-email-domains/disposable-email-domains" in text
    body = [line for line in text.splitlines() if not line.startswith("#")]
    assert body == sorted(body) and "a.example" in body


def test_a_major_provider_in_the_upstream_list_is_dropped_and_named(tmp_path):
    path, refresh = snapshot(tmp_path, list_text=upstream([*good_names(), "gmail.com", "sify.com", "Yahoo.com"]))

    result = refresh.refresh()

    names = {line for line in path.read_text(encoding="utf-8").splitlines() if not line.startswith("#")}
    assert not names & {"gmail.com", "sify.com", "yahoo.com"}
    assert result.removed == ("gmail.com", "sify.com", "yahoo.com")
    assert "Dropped, real mail providers that must never be blocked: gmail.com, sify.com, yahoo.com" in path.read_text()


def test_a_bare_suffix_is_never_kept_as_a_blocked_name(tmp_path):
    path, refresh = snapshot(tmp_path, list_text=upstream([*good_names(), "com", "uk"]))

    refresh.refresh()

    assert "com" not in path.read_text(encoding="utf-8").splitlines()


def test_a_list_too_small_to_be_right_is_refused_and_the_file_is_left_alone(tmp_path):
    path, refresh = snapshot(tmp_path, list_text=upstream(["only.example"]))

    with pytest.raises(SnapshotRefused, match="fewer than"):
        refresh.refresh()

    assert path.read_text(encoding="utf-8") == "# the old file\nold.example\n"


@pytest.mark.parametrize("kwargs", [{"list_status": 500}, {"commit_status": 403}, {"commit": {"no": "sha"}}])
def test_a_failed_fetch_is_refused_with_a_plain_reason_and_the_file_is_left_alone(tmp_path, kwargs):
    path, refresh = snapshot(tmp_path, **kwargs)

    with pytest.raises(SnapshotRefused):
        refresh.refresh()

    assert path.read_text(encoding="utf-8") == "# the old file\nold.example\n"
