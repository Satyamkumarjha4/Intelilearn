"""Unit under test: `accounts.identity.state` (`OAuthState`, `FinishState`) and `accounts.redirect.RedirectPolicy`:
the two signed cookies of the sign-in dance, the PKCE pair, and what `next` may be.

Why: the callback is a plain GET that anyone can point a browser at. What stops a forged callback, a replayed one, one
for another provider or one that sends the person to an attacker's site is the signed `lc_oauth` cookie (state, nonce,
PKCE verifier, where to go) and the rule that `next` is only ever a path on this site. A ticket that could be edited,
kept past its time or signed by another part of the app would defeat all of it.

Use cases:
- a ticket carries a fresh state, nonce and verifier each time, and the PKCE challenge is S256 of the verifier (RFC
  7636's own test vector)
- a sealed ticket reads back; a missing, forged, tampered, expired or wrongly salted one reads as nothing
- `check` accepts the state this browser sent and refuses a different state, no state, another provider's ticket and
  no ticket, each as `state_mismatch`
- the finish ticket carries the identity and where to go, reads back, and is refused when forged, expired or
  malformed
- `next` is kept only when it is a path on this site: `//evil.com`, `/\\evil.com`, a full URL, `javascript:`, a tab or
  newline inside, a control character and a non-string all fall back; a path with a query and a fragment is kept
"""

import base64
import hashlib

import pytest
from django.core import signing

from accounts.identity.provider import ProviderError, VerifiedIdentity
from accounts.identity.state import FinishState, FinishTicket, OAuthState
from accounts.redirect import RedirectPolicy


def test_every_ticket_is_fresh_and_the_challenge_is_the_s256_of_the_verifier():
    states = OAuthState()
    first, second = states.issue("google", "/lessons"), states.issue("google", "/lessons")

    assert (
        len({first.state, second.state})
        == len({first.nonce, second.nonce})
        == len({first.verifier, second.verifier})
        == 2
    )
    assert 43 <= len(first.verifier) <= 128  # RFC 7636's bounds
    expected = base64.urlsafe_b64encode(hashlib.sha256(first.verifier.encode()).digest()).rstrip(b"=").decode()
    assert first.challenge == expected


def test_the_challenge_matches_rfc_7636_appendix_b():
    from dataclasses import replace

    ticket = replace(OAuthState().issue("google", "/"), verifier="dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk")

    assert ticket.challenge == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_a_sealed_ticket_reads_back_and_anything_else_reads_as_nothing():
    states = OAuthState()
    ticket = states.issue("google", "/quizzes")
    cookie = states.seal(ticket)

    assert states.read(cookie) == ticket
    forged = signing.dumps({"provider": "google"}, salt="not-ours")
    for bad in (None, "", "garbage", cookie[:-3] + "abc", forged, cookie + "x"):
        assert states.read(bad) is None


def test_an_expired_ticket_reads_as_nothing(settings, monkeypatch):
    import time

    settings.OAUTH_STATE_MINUTES = 10
    states = OAuthState()
    cookie = states.seal(states.issue("google", "/"))
    assert states.read(cookie) is not None

    later = time.time() + 11 * 60
    monkeypatch.setattr("django.core.signing.time.time", lambda: later)

    assert states.read(cookie) is None


def test_check_accepts_the_state_this_browser_sent():
    states = OAuthState()
    ticket = states.issue("google", "/lessons")

    assert states.check(states.seal(ticket), ticket.state, "google") == ticket


@pytest.mark.parametrize("case", ["other state", "no state", "other provider", "no ticket", "forged ticket"])
def test_check_refuses_everything_else_as_state_mismatch(case):
    states = OAuthState()
    ticket = states.issue("google", "/lessons")
    cookie, returned, provider = states.seal(ticket), ticket.state, "google"
    if case == "other state":
        returned = states.issue("google", "/").state
    elif case == "no state":
        returned = ""
    elif case == "other provider":
        provider = "fake"
    elif case == "no ticket":
        cookie = None
    elif case == "forged ticket":
        cookie = cookie[:-4] + "AAAA"

    with pytest.raises(ProviderError) as refused:
        states.check(cookie, returned, provider)

    assert refused.value.code == "state_mismatch"


def test_next_on_a_new_ticket_goes_through_the_redirect_policy():
    states = OAuthState()

    assert states.issue("google", "//evil.com").next == "/lessons"
    assert states.issue("google", "https://evil.com/x").next == "/lessons"
    assert states.issue("google", "/quizzes/abc?tab=1").next == "/quizzes/abc?tab=1"


IDENTITY = VerifiedIdentity("google", "sub-1", "ada@example.com", True, "Ada", "school.ac.in")


def test_the_finish_ticket_carries_the_identity_and_where_to_go():
    finish = FinishState()
    cookie = finish.seal(FinishTicket(IDENTITY, "/quizzes"))

    ticket = finish.read(cookie)

    assert ticket == FinishTicket(IDENTITY, "/quizzes")


def test_a_finish_ticket_that_is_forged_expired_or_malformed_reads_as_nothing(monkeypatch):
    import time

    finish = FinishState()
    cookie = finish.seal(FinishTicket(IDENTITY, "/lessons"))
    other_salt = signing.dumps({"identity": {}, "next": "/"}, salt="accounts.oauth-state")
    wrong_shape = signing.dumps({"identity": {"nope": 1}, "next": "/"}, salt=FinishState.SALT)

    for bad in (None, "", "garbage", cookie[:-3] + "abc", other_salt, wrong_shape):
        assert finish.read(bad) is None
    later = time.time() + 16 * 60
    monkeypatch.setattr("django.core.signing.time.time", lambda: later)
    assert finish.read(cookie) is None


def test_a_finish_ticket_whose_next_was_not_safe_when_made_still_reads_safe():
    finish = FinishState()
    cookie = signing.dumps(
        {
            "identity": {"provider": "google", "subject": "s", "email": "a@b.co", "email_verified": True},
            "next": "//evil.com",
        },
        salt=FinishState.SALT,
        compress=False,
    )

    assert finish.read(cookie).next == "/lessons"


@pytest.mark.parametrize(
    ("value", "kept"),
    [
        ("/lessons", "/lessons"),
        ("/lessons/abc?tab=test&x=1", "/lessons/abc?tab=test&x=1"),
        ("/path#frag", "/path#frag"),
        ("/", "/"),
        ("//evil.com", None),
        ("//evil.com/path", None),
        ("/\\evil.com", None),
        ("\\\\evil.com", None),
        ("https://evil.com", None),
        ("http://evil.com/x", None),
        ("javascript:alert(1)", None),
        ("/\tevil.com", None),
        ("/\nevil.com", None),
        ("/ok\r\nSet-Cookie: x=1", None),
        ("/ok\x00", None),
        ("evil.com", None),
        ("", None),
        (None, None),
        (42, None),
        (["/lessons"], None),
    ],
)
def test_next_is_kept_only_when_it_is_a_path_on_this_site(value, kept):
    assert RedirectPolicy.safe_next(value) == (kept if kept is not None else "/lessons")


def test_the_fallback_can_be_chosen():
    assert RedirectPolicy.safe_next("//evil.com", "/") == "/"
    assert RedirectPolicy.safe_next(None, "/start") == "/start"
