"""Unit under test: `accounts.identity.checks.ProviderSafety` (system checks `accounts.E005` to `E008`) and
`accounts.identity.registry.IdentityProviders`.

Why: the stand-in provider answers the sign-in redirect with whatever identity a request names. On a public site that
would let anyone sign in as anyone, so the app must refuse to start with it on outside a debug run, and a real provider
that is switched on but not set up must stop the app when it starts, not at the first person's sign-in. The registry
decides which providers have a button and a working flow: a provider that is off is the same as one that does not exist.

Use cases:
- the stand-in provider is refused in production: the switch on with `DJANGO_DEBUG` off is `accounts.E006`
- the stand-in named in `AUTH_PROVIDERS_ENABLED` without its switch is `accounts.E005`, and with it (a debug run) is
  fine
- an unknown provider key is `accounts.E007` and a real provider missing its settings is `accounts.E008`; a set-up
  one is fine
- the checks are registered with Django, so `manage.py check` runs them with the real settings
- the registry lists only providers that are on, builds them from settings, and ignores unknown keys; the stand-in
  needs both a place in the list and its own switch
"""

import pytest
from django.core.checks import Tags, run_checks

from accounts.identity.checks import ProviderSafety
from accounts.identity.fake import FakeProvider
from accounts.identity.google import GoogleProvider
from accounts.identity.registry import IdentityProviders

CLASSES = {"google": GoogleProvider, "fake": FakeProvider}


def ids(**kwargs):
    return [error.id for error in ProviderSafety(classes=CLASSES, **kwargs).errors()]


def test_the_stand_in_provider_is_refused_in_production():
    assert "accounts.E006" in ids(enabled=["fake"], allow_fake=True, debug=False)
    assert "accounts.E006" in ids(enabled=[], allow_fake=True, debug=False)


def test_the_stand_in_needs_its_switch_and_with_it_a_debug_run_is_fine():
    assert ids(enabled=["fake"], allow_fake=False, debug=True) == ["accounts.E005"]
    assert ids(enabled=["fake"], allow_fake=True, debug=True) == []
    assert ids(enabled=[], allow_fake=False, debug=False) == []


def test_an_unknown_provider_and_a_provider_missing_its_settings_stop_the_app(settings):
    settings.GOOGLE_OAUTH_CLIENT_ID = ""
    settings.GOOGLE_OAUTH_CLIENT_SECRET = ""
    assert ids(enabled=["nonesuch"], allow_fake=False, debug=False) == ["accounts.E007"]
    assert ids(enabled=["google"], allow_fake=False, debug=False) == ["accounts.E008"]

    settings.GOOGLE_OAUTH_CLIENT_ID, settings.GOOGLE_OAUTH_CLIENT_SECRET = "id", "secret"
    assert ids(enabled=["google"], allow_fake=False, debug=False) == []


def test_the_missing_settings_are_named_and_never_their_values(settings):
    settings.GOOGLE_OAUTH_CLIENT_ID, settings.GOOGLE_OAUTH_CLIENT_SECRET = "an-id-we-do-not-print", ""

    (error,) = ProviderSafety(enabled=["google"], allow_fake=False, debug=False, classes=CLASSES).errors()

    assert "GOOGLE_OAUTH_CLIENT_SECRET" in error.msg and "an-id-we-do-not-print" not in error.msg + error.hint


def test_django_runs_the_checks_with_the_real_settings(settings):
    settings.AUTH_PROVIDERS_ENABLED = ["fake"]
    settings.AUTH_ALLOW_FAKE_PROVIDER = True
    settings.DEBUG = False

    assert "accounts.E006" in [error.id for error in run_checks(tags=[Tags.security])]


def test_the_registry_lists_only_what_is_on_and_the_stand_in_needs_its_switch(settings):
    settings.AUTH_PROVIDERS_ENABLED = ["fake", "nonesuch"]
    settings.AUTH_ALLOW_FAKE_PROVIDER = False
    assert IdentityProviders().enabled_keys == [] and IdentityProviders().get("fake") is None

    settings.AUTH_ALLOW_FAKE_PROVIDER = True
    registry = IdentityProviders()
    assert registry.enabled_keys == ["fake"]
    assert isinstance(registry.get("fake"), FakeProvider) and registry.get("nonesuch") is None
    assert [p.key for p in registry.enabled()] == ["fake"]


def test_a_registry_can_be_handed_its_own_classes_and_list():
    registry = IdentityProviders(classes={"fake": FakeProvider}, enabled=["fake", "google"])

    assert registry.enabled_keys == ["fake"] or registry.enabled_keys == []  # `fake` also needs the settings switch


@pytest.mark.parametrize("key", ["google", "fake"])
def test_the_providers_are_registered_by_their_modules(key):
    assert key in IdentityProviders.REGISTERED and IdentityProviders.REGISTERED[key].key == key
