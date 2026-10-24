"""Unit under test: `core.checks.DeploySecurityChecks`, through the `secret_key_check` hook run by `check --deploy`.

Why: the development SECRET_KEY is public (it's in the repository). A deployment running with it would let anyone
sign their own JWTs and sign in as any user.

Use cases:
- the development secret key fails the deploy check (core.E001)
- a real secret key passes
- the keys can be injected for a unit test
"""

from core.checks import DeploySecurityChecks, secret_key_check


def test_development_secret_key_fails_the_deploy_check(settings):
    settings.SECRET_KEY = settings.DEV_SECRET_KEY
    assert [e.id for e in secret_key_check()] == ["core.E001"]


def test_real_secret_key_passes(settings):
    settings.SECRET_KEY = "a-long-random-production-value-" + "x" * 30
    assert secret_key_check() == []


def test_keys_can_be_injected():
    assert [e.id for e in DeploySecurityChecks(secret_key="dev", dev_secret_key="dev").errors()] == ["core.E001"]
    assert DeploySecurityChecks(secret_key="prod-key", dev_secret_key="dev").errors() == []
