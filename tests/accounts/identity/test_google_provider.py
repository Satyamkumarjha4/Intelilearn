"""Unit under test: `accounts.identity.google.GoogleProvider`, the server-side authorization-code flow with Google
(plan T5, T6).

Why: this class is where Google's answer becomes "this is who is signing in". It must send what Google needs (state,
nonce, a PKCE challenge, the exact redirect address), exchange the code itself with the client secret and the PKCE
verifier so no token reaches the browser, check the ID token, and call an address verified only when Google says so
with the boolean `true`. Every failure is one of the five codes the sign-in page knows, and none of them carries a
token, a code, a secret or Google's error text. Google is a `support/oidc.py` double that signs real tokens: nothing
here touches the network.

Use cases:
- the start address carries the client id, the exact redirect address, `response_type=code`, the three scopes, the
  state, the nonce, an S256 PKCE challenge of the ticket's verifier, and `prompt=select_account`
- a good callback exchanges the code (sending the client secret, the redirect address and the PKCE verifier) and
  returns a verified identity keyed by `sub`, with the name and hosted domain
- an `error=access_denied` callback, a missing code, a token endpoint that refuses or fails, an answer with no ID
  token, and a token that fails any check (wrong nonce, audience, signature) are each `sign_in_failed`
- **`email_verified` is accepted as the boolean `true` or the exact string `"true"`**; anything else (`false`,
  `"false"`, `"True"`, `1`, missing, `null`) is `email_not_verified`, and so is a missing email
- the refusal text never holds a token, a secret or Google's error description
- the provider reports the settings it lacks
"""

import httpx
import pytest
from support.oidc import CLIENT_ID, KID, MISSING, FakeGoogle

from accounts.identity.google import GoogleProvider
from accounts.identity.provider import ProviderError
from accounts.identity.state import OAuthState
from accounts.identity.tokens import StaticJwks

REDIRECT = "https://socra.test/api/auth/oauth/google/callback"
SECRET = "client-secret-never-to-be-logged"


@pytest.fixture
def google():
    return FakeGoogle()


@pytest.fixture
def ticket():
    return OAuthState().issue("google", "/lessons/abc")


def provider(google):
    return GoogleProvider(CLIENT_ID, SECRET, http=google.client(), jwks=StaticJwks({KID: google.key.public_key()}))


def callback(google, ticket, claims=None, **params):
    """Run `complete` for a Google that will answer the token request with a token made from `claims`."""
    google.id_token = google.sign(claims if claims is not None else google.claims(ticket.nonce))
    return provider(google).complete({"code": "4/auth-code", "state": ticket.state, **params}, ticket, REDIRECT)


def failure(google, ticket, **kwargs):
    with pytest.raises(ProviderError) as error:
        callback(google, ticket, **kwargs)
    return error.value


def test_the_start_address_carries_everything_google_needs(google, ticket):
    url = provider(google).start(ticket, REDIRECT, {})

    base, _, query = url.partition("?")
    params = dict(pair.split("=", 1) for pair in query.split("&"))
    assert base == "https://accounts.google.com/o/oauth2/v2/auth"
    assert params["client_id"] == CLIENT_ID and params["response_type"] == "code"
    assert params["redirect_uri"] == "https%3A%2F%2Fsocra.test%2Fapi%2Fauth%2Foauth%2Fgoogle%2Fcallback"
    assert params["scope"] == "openid+email+profile"
    assert params["state"] == ticket.state and params["nonce"] == ticket.nonce
    assert params["code_challenge"] == ticket.challenge and params["code_challenge_method"] == "S256"
    assert params["prompt"] == "select_account"
    assert SECRET not in url and ticket.verifier not in url  # the secret and the verifier never go in the address


def test_a_good_callback_exchanges_the_code_itself_and_returns_a_verified_identity(google, ticket):
    claims = google.claims(ticket.nonce, hd="school.ac.in", sub="google-sub-9", email="Ada.L@School.ac.in")

    identity = callback(google, ticket, claims)

    assert (identity.provider, identity.subject, identity.email) == ("google", "google-sub-9", "Ada.L@School.ac.in")
    assert identity.email_verified and identity.name == "Ada Lovelace" and identity.hosted_domain == "school.ac.in"
    (sent,) = google.requests
    assert sent["code"] == "4%2Fauth-code" and sent["grant_type"] == "authorization_code"
    assert sent["client_id"] == CLIENT_ID and sent["client_secret"] == SECRET
    assert sent["code_verifier"] == ticket.verifier  # the PKCE proof the challenge was made from
    assert sent["redirect_uri"] == "https%3A%2F%2Fsocra.test%2Fapi%2Fauth%2Foauth%2Fgoogle%2Fcallback"


def test_a_person_who_says_no_at_google_is_sign_in_failed(google, ticket):
    refused = failure(google, ticket, error="access_denied")

    assert refused.code == "sign_in_failed" and google.requests == []  # nothing was exchanged


def test_a_callback_with_no_code_is_sign_in_failed(google, ticket):
    with pytest.raises(ProviderError) as error:
        provider(google).complete({"state": ticket.state}, ticket, REDIRECT)

    assert error.value.code == "sign_in_failed"


@pytest.mark.parametrize("status", [400, 401, 500, 503])
def test_a_token_endpoint_that_refuses_is_sign_in_failed_and_google_s_words_are_not_kept(google, ticket, status):
    google.token_status = status

    refused = failure(google, ticket)

    assert refused.code == "sign_in_failed" and str(status) in refused.detail
    assert "secret-detail" not in str(refused) and "invalid_grant" not in str(refused)


def test_a_token_endpoint_that_cannot_be_reached_is_sign_in_failed(ticket):
    def down(request):
        raise httpx.ConnectError("no route")

    unreachable = GoogleProvider(CLIENT_ID, SECRET, http=httpx.Client(transport=httpx.MockTransport(down)))

    with pytest.raises(ProviderError) as error:
        unreachable.complete({"code": "c"}, ticket, REDIRECT)

    assert error.value.code == "sign_in_failed" and "ConnectError" in error.value.detail


def test_an_answer_with_no_id_token_is_sign_in_failed(google, ticket):
    google.id_token = None
    handler_provider = GoogleProvider(
        CLIENT_ID, SECRET, jwks=StaticJwks({}),
        http=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"access_token": "x"}))),
    )  # fmt: skip

    with pytest.raises(ProviderError) as error:
        handler_provider.complete({"code": "c"}, ticket, REDIRECT)

    assert error.value.code == "sign_in_failed"


@pytest.mark.parametrize(
    "tamper",
    [
        pytest.param(lambda g, t: g.claims("another-sign-in"), id="wrong nonce"),
        pytest.param(lambda g, t: g.claims(t.nonce, aud="someone-else"), id="wrong audience"),
        pytest.param(lambda g, t: g.claims(t.nonce, iss="https://evil.example"), id="wrong issuer"),
        pytest.param(lambda g, t: g.claims(t.nonce, exp=1), id="expired"),
    ],
)
def test_a_token_that_fails_a_check_is_sign_in_failed(google, ticket, tamper):
    refused = failure(google, ticket, claims=tamper(google, ticket))

    assert refused.code == "sign_in_failed" and "id token refused" in refused.detail


def test_a_token_signed_with_another_key_is_sign_in_failed(google, ticket):
    other = FakeGoogle()  # a different key pair: not the keys this provider trusts
    google.id_token = other.sign(google.claims(ticket.nonce))

    with pytest.raises(ProviderError) as error:
        provider(google).complete({"code": "c"}, ticket, REDIRECT)

    assert error.value.code == "sign_in_failed" and "InvalidSignatureError" in error.value.detail


@pytest.mark.parametrize("verified", [True, "true"], ids=["boolean true", 'the exact string "true"'])
def test_an_email_google_calls_verified_is_accepted_as_the_boolean_true_or_the_exact_string_true(
    google, ticket, verified
):
    """Google's own example shows the string; its tokens are reported to carry the boolean. Either says yes."""
    identity = callback(google, ticket, claims=google.claims(ticket.nonce, email_verified=verified))

    assert identity.email_verified


@pytest.mark.parametrize(
    "verified",
    [False, MISSING, None, "True", "TRUE", " true", "true ", 1, "false", "", "yes", [True]],
    ids=[
        "false", "missing", "null", "string True", "string TRUE", "padded left", "padded right", "number 1",
        "string false", "empty", "string yes", "list",
    ],
)  # fmt: skip
def test_anything_else_is_not_google_calling_the_email_verified(google, ticket, verified):
    refused = failure(google, ticket, claims=google.claims(ticket.nonce, email_verified=verified))

    assert refused.code == "email_not_verified"


@pytest.mark.parametrize("email", [MISSING, "", None, 12345])
def test_a_missing_or_unusable_email_is_email_not_verified(google, ticket, email):
    assert failure(google, ticket, claims=google.claims(ticket.nonce, email=email)).code == "email_not_verified"


def test_the_refusal_text_never_holds_a_token_a_secret_or_a_code(google, ticket):
    google.token_status = 400
    refused = failure(google, ticket)
    claims = google.claims("wrong-nonce")
    bad_token = failure(google, ticket, claims=claims)
    text = f"{refused} {refused.detail} {bad_token} {bad_token.detail}"

    for secret in (SECRET, ticket.verifier, ticket.nonce, "4/auth-code", google.id_token or "-", "secret-detail"):
        assert secret not in text


def test_the_provider_reports_the_settings_it_lacks():
    assert GoogleProvider("", "").missing_config() == ["GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET"]
    assert GoogleProvider("id", "").missing_config() == ["GOOGLE_OAUTH_CLIENT_SECRET"]
    assert GoogleProvider("id", "secret").missing_config() == []
