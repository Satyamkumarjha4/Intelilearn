"""Unit under test: `accounts.identity.tokens` (`IdTokenValidator`, `HttpJwks`, `StaticJwks`), the check of an OpenID
Connect ID token (plan T11).

Why: the ID token is the whole proof that a person is who the provider says. A validator that accepts a token it should
not (an unsigned one, one signed with the wrong key or algorithm, one meant for another app, an old one, one for
another sign-in) lets anyone sign in as anyone. So every check is a test against tokens signed with a REAL key pair
(`support/oidc.py`): the good token passes, and each thing that can be wrong is wrong on its own and is refused. The
keys are fetched and cached the way a provider's keys are, and a key we cannot find is never guessed.

Use cases:
- a good token passes and returns its claims; both issuers Google documents are accepted
- a wrong signature, `alg: none`, an unsigned token, an algorithm that is not on the list (HS256 signed with the public
  key) and garbage are each refused
- a wrong audience, a wrong issuer, an expired token, a missing expiry and a missing subject are each refused
- a wrong nonce, a missing nonce claim and an empty expected nonce are each refused (the nonce is always checked)
- a subject that is not text, is empty or is longer than 255 characters is refused
- an unknown `kid` is refused; a token with no `kid` is refused
- `HttpJwks` fetches once and caches for the response's `max-age` (an hour when it says nothing), refetches an
  unknown `kid` at most once a minute, ignores keys that are not RSA, and turns a failed fetch into a refusal
- `StaticJwks` finds its keys and raises `KeyError` for the rest
"""

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from support.oidc import CLIENT_ID, KID, MISSING, FakeGoogle

from accounts.identity.tokens import HttpJwks, IdTokenValidator, InvalidIdToken, StaticJwks

ISSUERS = frozenset({"https://accounts.google.com", "accounts.google.com"})
NONCE = "a-nonce-this-browser-made"


@pytest.fixture
def google():
    return FakeGoogle()


@pytest.fixture
def validator():
    return IdTokenValidator(ISSUERS, CLIENT_ID)


@pytest.fixture
def jwks(google):
    return StaticJwks({KID: google.key.public_key()})


def refused(validator, token, jwks, nonce=NONCE):
    with pytest.raises(InvalidIdToken) as error:
        validator.validate(token, jwks, nonce)
    return error.value.reason


def test_a_good_token_passes_and_returns_its_claims(google, validator, jwks):
    claims = validator.validate(google.sign(google.claims(NONCE)), jwks, NONCE)

    assert claims["sub"] == "10769150350006150715113082367" and claims["email"] == "ada@example.com"


@pytest.mark.parametrize("issuer", ["https://accounts.google.com", "accounts.google.com"])
def test_both_issuers_google_documents_are_accepted(google, validator, jwks, issuer):
    assert validator.validate(google.sign(google.claims(NONCE, iss=issuer)), jwks, NONCE)["iss"] == issuer


def test_a_token_signed_with_another_key_is_refused(google, validator, jwks):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    assert refused(validator, google.sign(google.claims(NONCE), key=other), jwks) == "InvalidSignatureError"


def test_alg_none_is_refused_before_any_key_is_looked_up(google, validator):
    class NoKeys:
        def key_for(self, kid):
            raise AssertionError("a key was looked up for an unacceptable algorithm")

    assert "'none' is not accepted" in refused(validator, google.unsigned(google.claims(NONCE)), NoKeys())


def test_a_token_with_its_signature_cut_off_is_refused(google, validator, jwks):
    assert refused(validator, google.stripped(google.claims(NONCE)), jwks)


def test_an_hmac_token_signed_with_the_public_key_is_refused(google, validator, jwks):
    """The classic downgrade: HS256 with the RSA public key as the secret. The algorithm is not on our list."""
    public_pem = google.key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    token = google.hmac_token(google.claims(NONCE), public_pem)

    assert "'HS256' is not accepted" in refused(validator, token, jwks)


@pytest.mark.parametrize("garbage", ["", "not-a-token", "a.b.c", "....", "eyJhbGciOiJSUzI1NiJ9.e30."])
def test_garbage_is_refused(validator, jwks, garbage):
    assert refused(validator, garbage, jwks)


def test_a_token_for_another_app_is_refused(google, validator, jwks):
    assert (
        refused(validator, google.sign(google.claims(NONCE, aud="someone-elses-client")), jwks)
        == "InvalidAudienceError"
    )


def test_a_token_with_a_list_audience_that_holds_ours_passes_and_one_without_it_does_not(google, validator, jwks):
    assert validator.validate(google.sign(google.claims(NONCE, aud=[CLIENT_ID, "other"])), jwks, NONCE)
    assert refused(validator, google.sign(google.claims(NONCE, aud=["a", "b"])), jwks) == "InvalidAudienceError"


@pytest.mark.parametrize(
    "issuer", ["https://evil.example", "accounts.google.com.evil.example", "http://accounts.google.com"]
)
def test_a_wrong_issuer_is_refused(google, validator, jwks, issuer):
    assert refused(validator, google.sign(google.claims(NONCE, iss=issuer)), jwks) == "wrong issuer"


def test_an_expired_token_is_refused_and_a_token_expired_a_moment_ago_is_within_the_leeway(google, validator, jwks):
    import time

    long_ago = google.sign(google.claims(NONCE, exp=int(time.time()) - 3600, iat=int(time.time()) - 7200))
    just_now = google.sign(google.claims(NONCE, exp=int(time.time()) - 5))

    assert refused(validator, long_ago, jwks) == "ExpiredSignatureError"
    assert validator.validate(just_now, jwks, NONCE)  # a minute's clock difference between servers is not an attack


@pytest.mark.parametrize("claim", ["exp", "iat", "sub", "iss", "aud"])
def test_a_token_missing_a_required_claim_is_refused(google, validator, jwks, claim):
    assert (
        refused(validator, google.sign(google.claims(NONCE, **{claim: MISSING})), jwks) == "MissingRequiredClaimError"
    )


def test_a_wrong_nonce_is_refused(google, validator, jwks):
    assert refused(validator, google.sign(google.claims("another-sign-in")), jwks) == "wrong nonce"


def test_a_token_with_no_nonce_claim_is_refused(google, validator, jwks):
    claims = google.claims(NONCE)
    del claims["nonce"]

    assert refused(validator, google.sign(claims), jwks) == "wrong nonce"


def test_an_empty_expected_nonce_is_refused_even_for_a_token_with_an_empty_nonce(google, validator, jwks):
    assert refused(validator, google.sign(google.claims("")), jwks, nonce="") == "no nonce to check against"


@pytest.mark.parametrize("subject", [12345, "", "x" * 256, None, ["a"]])
def test_a_subject_that_is_not_a_usable_id_is_refused(google, validator, jwks, subject):
    assert refused(validator, google.sign(google.claims(NONCE, sub=subject)), jwks)


def test_a_subject_of_255_characters_passes(google, validator, jwks):
    assert validator.validate(google.sign(google.claims(NONCE, sub="x" * 255)), jwks, NONCE)


def test_an_unknown_kid_and_a_missing_kid_are_refused(google, validator, jwks):
    assert refused(validator, google.sign(google.claims(NONCE), kid="rotated-away"), jwks) == "no key for this token"
    assert refused(validator, google.sign(google.claims(NONCE), kid=None), jwks) == "no key for this token"


# --- the keys ---


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_the_keys_are_fetched_once_and_kept_for_the_max_age(google):
    clock = Clock()
    google.cache_control = "public, max-age=600"
    source = HttpJwks(google.client(), "https://example.test/oauth2/v3/certs", clock)

    first = source.key_for(KID)
    clock.now += 599
    assert source.key_for(KID).public_numbers() == first.public_numbers() and google.jwks_fetches == 1

    clock.now += 2  # past the max-age
    source.key_for(KID)
    assert google.jwks_fetches == 2


def test_with_no_cache_header_the_keys_are_kept_an_hour(google):
    clock = Clock()
    source = HttpJwks(google.client(), "https://example.test/oauth2/v3/certs", clock)
    source.key_for(KID)

    clock.now += 3599
    source.key_for(KID)
    assert google.jwks_fetches == 1
    clock.now += 2
    source.key_for(KID)
    assert google.jwks_fetches == 2


def test_an_unknown_kid_refetches_at_most_once_a_minute(google):
    clock = Clock()
    source = HttpJwks(google.client(), "https://example.test/oauth2/v3/certs", clock)
    source.key_for(KID)

    for _ in range(5):
        with pytest.raises(KeyError):
            source.key_for("made-up-by-an-attacker")
    assert google.jwks_fetches == 1  # not one fetch per forged token

    clock.now += 61
    with pytest.raises(KeyError):
        source.key_for("made-up-by-an-attacker")
    assert google.jwks_fetches == 2  # a real rotation is picked up once the floor has passed


def test_keys_that_are_not_rsa_are_ignored(google):
    import httpx

    document = {
        "keys": [{"kty": "EC", "kid": "ec-key", "crv": "P-256", "x": "AA", "y": "AA"}, google.jwks()["keys"][0]]
    }
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=document)))
    source = HttpJwks(client, "https://example.test/certs", Clock())

    assert source.key_for(KID)
    with pytest.raises(KeyError):
        source.key_for("ec-key")


@pytest.mark.parametrize("answer", ["error", "garbage", "no-keys"])
def test_a_failed_fetch_is_a_refusal_not_a_crash(answer):
    import httpx

    def handler(request):
        if answer == "error":
            return httpx.Response(503)
        if answer == "garbage":
            return httpx.Response(200, text="<html>not json</html>")
        return httpx.Response(200, json={"nothing": []})

    source = HttpJwks(httpx.Client(transport=httpx.MockTransport(handler)), "https://example.test/certs", Clock())

    with pytest.raises(InvalidIdToken, match="keys could not be fetched"):
        source.key_for(KID)


def test_static_keys_find_theirs_and_raise_key_error_for_the_rest(google):
    keys = StaticJwks({KID: google.key.public_key()})

    assert keys.key_for(KID)
    for kid in ("other", None):
        with pytest.raises(KeyError):
            keys.key_for(kid)
