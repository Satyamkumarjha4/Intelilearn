"""Unit under test: `OAuthSignIn` with several real threads (and so several database connections) at once.

Why: two people, or one person's two tabs, can come back from the provider at the same instant. The rules that must
hold then are database rules (an advisory lock and two unique constraints), and a single-threaded test cannot tell a
rule from no rule. So these use real threads and real transactions (`transaction=True`) and check what must hold in
every interleaving.

Use cases:
- **simultaneous last steps for one new identity make one account**, one link and one grant
- simultaneous callbacks for one new identity create nothing: each is told to take the last step
- simultaneous callbacks that take over one never-verified account take it over once: one link, one grant
- a callback and simultaneous last steps for the same new person never make two accounts
"""

import pytest
from support.threads import together

from accounts.identity.fake import FakeProvider
from accounts.identity.signin import OAuthSignIn
from accounts.identity.state import FinishState, FinishTicket
from accounts.models import ExternalIdentity, User
from credits.models import CreditBucket

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def _fake_provider_on(settings):
    settings.AUTH_PROVIDERS_ENABLED = ["fake"]
    settings.AUTH_ALLOW_FAKE_PROVIDER = True


def identity(subject="sub-1", email="ada@example.com"):
    return FakeProvider().complete({"code": _code(subject, email)}, ticket=None, redirect_uri="x")


def _code(subject, email):
    import base64
    import json

    data = {"subject": subject, "email": email, "email_verified": True, "name": "Ada"}
    return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")


def finish_cookie(who):
    return FinishState().seal(FinishTicket(who, "/lessons"))


def test_two_simultaneous_last_steps_for_one_new_identity_make_one_account_one_link_and_one_grant():
    cookie = finish_cookie(identity())

    results = together([lambda: OAuthSignIn().finish(cookie, "Ada", True, "", None) for _ in range(6)])

    assert not any(isinstance(r, Exception) for r in results), results
    assert all(r.kind == "signed_in" for r in results)
    assert User.objects.filter(email_canonical="ada@example.com").count() == 1
    assert ExternalIdentity.objects.count() == 1 and CreditBucket.objects.filter(source="signup").count() == 1


def test_two_simultaneous_callbacks_for_one_new_identity_create_nothing_and_each_goes_to_the_last_step():
    sign_in = OAuthSignIn()
    who = identity()

    results = together([lambda: sign_in._resolve(who, "/lessons") for _ in range(4)])

    assert not any(isinstance(r, Exception) for r in results), results
    assert all(r.kind == "finish" for r in results)
    assert not User.objects.exists() and not ExternalIdentity.objects.exists()


def test_simultaneous_callbacks_that_take_over_one_unverified_account_take_it_over_once():
    victim = User.objects.create_user("ada@example.com", password="a-long-password-1", name="Pre-made")
    who = identity()

    results = together([lambda: OAuthSignIn()._resolve(who, "/lessons") for _ in range(4)])

    assert not any(isinstance(r, Exception) for r in results), results
    assert all(r.kind in ("signed_in", "error") for r in results)
    assert ExternalIdentity.objects.filter(user=victim).count() == 1
    assert CreditBucket.objects.filter(user=victim, source="signup").count() == 1
    victim.refresh_from_db()
    assert not victim.has_usable_password() and victim.email_verification_source == "google"


def test_a_callback_and_a_last_step_for_the_same_new_person_never_make_two_accounts():
    who = identity()
    cookie = finish_cookie(who)

    results = together(
        [
            lambda: OAuthSignIn()._resolve(who, "/lessons"),
            lambda: OAuthSignIn().finish(cookie, "Ada", True, "", None),
            lambda: OAuthSignIn().finish(cookie, "Ada", True, "", None),
        ]
    )

    assert not any(isinstance(r, Exception) for r in results), results
    assert User.objects.filter(email_canonical="ada@example.com").count() == 1
    assert CreditBucket.objects.filter(source="signup").count() == 1
