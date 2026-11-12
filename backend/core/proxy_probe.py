"""A deploy-time probe: which `X-Forwarded-For` entry does Django count as the visitor's address?

Every per-address limit (sign-up, login, code sends) counts by the address the proxy chain hands to Django. This class
sends a forged header through the real front door (the public URL, or the Next proxy in development) and reads, from the
shared throttle cache, which of the addresses it sent was counted. It is what `manage.py probe_forwarded_header` runs;
the command's job is only to build it and print the report.
"""

import random
from dataclasses import dataclass

import httpx
from django.core.cache import caches

LOGIN_PATH = "/api/auth/login"
CSRF_PATH = "/api/auth/csrf"
THROTTLE_SCOPE = "auth"  # the per-address scope `login` and `register` share
CACHE_KEY = "throttle_%(scope)s_%(ident)s"  # DRF's `SimpleRateThrottle.cache_format`


@dataclass(frozen=True)
class ProbeFinding:
    """One forged header, and what came of it."""

    name: str
    header: str
    forged: str  # the address a client chose: counting it means the limit can be dodged
    counted: str | None  # the address that was counted, when it is one the probe sent; None when it was another
    passed: bool
    meaning: str


@dataclass(frozen=True)
class ProbeReport:
    findings: tuple[ProbeFinding, ...]

    @property
    def passed(self) -> bool:
        return all(finding.passed for finding in self.findings)


class ForwardedHeaderProbe:
    """Sends the forged headers and reads the throttle cache. The HTTP client and the cache are injected."""

    def __init__(self, client: httpx.Client, cache=None, scope: str = THROTTLE_SCOPE, rng: random.Random | None = None):
        self.client = client
        self.cache = cache if cache is not None else caches["default"]
        self.scope = scope
        self.rng = rng or random.SystemRandom()

    def run(self, base_url: str) -> ProbeReport:
        base = base_url.rstrip("/")
        csrf = self._csrf_token(base)
        # TEST-NET addresses (RFC 5737): never a real visitor, and a fresh one each run so no old counter is read.
        single = f"198.51.100.{self.rng.randint(1, 254)}"
        chosen = f"198.51.100.{self.rng.randint(1, 254)}"
        edge = f"203.0.113.{self.rng.randint(1, 254)}"
        keys = []
        findings = []
        for name, header, forged in (
            ("a single forged entry", single, single),
            ("a forged entry first, an edge's entry last", f"{chosen}, {edge}", chosen),
        ):
            self._login(base, csrf, header)
            counted = next((a for a in (forged, edge) if self.cache.get(self._key(a)) is not None), None)
            keys.extend(self._key(a) for a in (forged, edge))
            findings.append(self._finding(name, header, forged, counted))
        self.cache.delete_many(keys)  # leave no counters behind
        return ProbeReport(tuple(findings))

    def _finding(self, name: str, header: str, forged: str, counted: str | None) -> ProbeFinding:
        passed = counted != forged
        if name.startswith("a single"):
            meaning = (
                "counted another address: the front door replaced the header, as it must"
                if passed
                else "the visitor chose its own address: nothing in front overwrites the header (needs an edge)"
            )
        else:
            meaning = (
                "the forged first entry was not counted"
                if passed
                else "the proxy counted the entry the client chose, the first"
            )
        return ProbeFinding(name, header, forged, counted, passed, meaning)

    def _csrf_token(self, base: str) -> str:
        self.client.get(f"{base}{CSRF_PATH}")
        return self.client.cookies.get("csrftoken", "")

    def _login(self, base: str, csrf: str, forwarded_for: str) -> None:
        # An unknown address of an invalid domain: the request is refused (401) and changes nothing, but it is counted.
        self.client.post(
            f"{base}{LOGIN_PATH}",
            json={"email": "probe@forwarded-header.invalid", "password": "not-a-real-password"},
            headers={"X-CSRFToken": csrf, "X-Forwarded-For": forwarded_for},
        )

    def _key(self, address: str) -> str:
        return CACHE_KEY % {"scope": self.scope, "ident": address}
