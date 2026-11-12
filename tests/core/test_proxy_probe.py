"""Unit under test: `core.proxy_probe.ForwardedHeaderProbe`, the deploy-time check behind
`manage.py probe_forwarded_header`.

Why: every per-address limit counts the address the proxy chain hands to Django, and whether a visitor can choose it
depends on the edge in front of the app, which no unit test of ours can see. The probe asks the real front door after
a deploy. Its own logic is small but its verdict is what an operator trusts, so it is proved against fake front doors
that behave each way (an `httpx.MockTransport` that counts the address the way Django's throttle would).

Use cases:
- a front door that overwrites the header (the edge's address is counted) passes both cases
- a front door that counts the last entry passes (a forged first entry is not counted) but fails the single-entry case
  when that one entry is what is counted, which is the unfixable residual an edge must close
- a front door that counts the first entry fails the forged-first case
- the probe sends the CSRF header and the forwarded header it names, and leaves no counter behind
- each run uses fresh addresses, so an old counter is never read as this run's
"""

import random

import httpx
import pytest
from django.core.cache import caches

from core.proxy_probe import ForwardedHeaderProbe


class FrontDoor:
    """A fake site: `/api/auth/csrf` sets the cookie, `/api/auth/login` counts one address into the throttle cache."""

    def __init__(self, cache, pick):
        self.cache = cache
        self.pick = pick  # from the sent entries, the address that gets counted (or None for the edge's own)
        self.logins = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth/csrf":
            return httpx.Response(204, headers={"Set-Cookie": "csrftoken=abc123; Path=/"})
        sent = [part.strip() for part in request.headers.get("x-forwarded-for", "").split(",") if part.strip()]
        self.logins.append((request.headers.get("x-csrftoken"), sent))
        counted = self.pick(sent) or "192.0.2.1"  # the edge's own address when nothing the client sent is used
        self.cache.set(f"throttle_auth_{counted}", [1], 60)
        return httpx.Response(401, json={"detail": "invalid credentials"})


@pytest.fixture
def cache():
    cache = caches["default"]
    cache.clear()
    return cache


def _probe(cache, pick, seed=1):
    door = FrontDoor(cache, pick)
    client = httpx.Client(transport=httpx.MockTransport(door))
    return door, ForwardedHeaderProbe(client, cache=cache, rng=random.Random(seed))


def test_a_front_door_that_overwrites_the_header_passes_both_cases(cache):
    _, probe = _probe(cache, pick=lambda sent: None)

    report = probe.run("http://site.test")

    assert report.passed
    assert [f.counted for f in report.findings] == [None, None]


def test_a_front_door_that_counts_the_last_entry_passes_the_forged_first_case_and_fails_the_single_one(cache):
    _, probe = _probe(cache, pick=lambda sent: sent[-1])

    report = probe.run("http://site.test")

    single, pair = report.findings
    assert not single.passed  # one forged entry is counted whole: only an edge can stop that
    assert "nothing in front overwrites" in single.meaning
    assert pair.passed
    assert pair.counted == pair.header.split(", ")[1]  # the entry the "edge" appended
    assert not report.passed


def test_a_front_door_that_counts_the_first_entry_fails_the_forged_first_case(cache):
    _, probe = _probe(cache, pick=lambda sent: sent[0])

    report = probe.run("http://site.test")

    pair = report.findings[1]
    assert not pair.passed
    assert pair.counted == pair.forged
    assert "the first" in pair.meaning


def test_the_probe_sends_the_csrf_header_and_its_forged_entries_and_leaves_no_counter_behind(cache):
    door, probe = _probe(cache, pick=lambda sent: sent[0])

    report = probe.run("http://site.test/")  # a trailing slash on the base is tolerated

    assert [tokens for tokens, _ in door.logins] == ["abc123", "abc123"]
    assert [", ".join(sent) for _, sent in door.logins] == [f.header for f in report.findings]
    assert all(cache.get(f"throttle_auth_{address}") is None for _, sent in door.logins for address in sent)


def test_every_run_uses_fresh_addresses(cache):
    _, first = _probe(cache, pick=lambda sent: None, seed=1)
    _, second = _probe(cache, pick=lambda sent: None, seed=2)

    assert [f.header for f in first.run("http://site.test").findings] != [
        f.header for f in second.run("http://site.test").findings
    ]
