"""Unit under test: `core.checks.DeploySecurityChecks`, through the `secret_key_check` and `trusted_proxy_check` hooks
run by `check --deploy`.

Why: the development SECRET_KEY is public (it's in the repository). A deployment running with it would let anyone
sign their own JWTs and sign in as any user. And every per-address limit (sign-up, login, code sends) counts by the
client address that the proxy chain hands to Django, which is only right when the operator has said how many proxies
stand in front: left at the development default, a deployment may count every visitor as the edge proxy, or trust an
address the client chose.

Use cases:
- the development secret key fails the deploy check (core.E001)
- a real secret key passes
- the keys can be injected for a unit test
- a deployment (DEBUG off) that never set TRUSTED_PROXY_COUNT fails the deploy check (core.E002)
- one that set it, and a development run (DEBUG on), pass
"""

from core.checks import DeploySecurityChecks, secret_key_check, trusted_proxy_check


def test_development_secret_key_fails_the_deploy_check(settings):
    settings.SECRET_KEY = settings.DEV_SECRET_KEY
    assert [e.id for e in secret_key_check()] == ["core.E001"]


def test_real_secret_key_passes(settings):
    settings.SECRET_KEY = "a-long-random-production-value-" + "x" * 30
    assert secret_key_check() == []


def test_keys_can_be_injected():
    assert [e.id for e in DeploySecurityChecks(secret_key="dev", dev_secret_key="dev").secret_key()] == ["core.E001"]
    assert DeploySecurityChecks(secret_key="prod-key", dev_secret_key="dev").secret_key() == []


def test_a_deployment_that_never_set_the_proxy_count_fails_the_deploy_check(settings):
    settings.DEBUG = False
    settings.TRUSTED_PROXY_COUNT_EXPLICIT = False
    assert [e.id for e in trusted_proxy_check()] == ["core.E002"]


def test_a_deployment_that_set_the_proxy_count_passes(settings):
    settings.DEBUG = False
    settings.TRUSTED_PROXY_COUNT_EXPLICIT = True
    assert trusted_proxy_check() == []


def test_a_development_run_does_not_need_the_proxy_count(settings):
    settings.DEBUG = True
    settings.TRUSTED_PROXY_COUNT_EXPLICIT = False
    assert trusted_proxy_check() == []


def test_the_proxy_facts_can_be_injected():
    assert [e.id for e in DeploySecurityChecks(debug=False, proxy_count_explicit=False).proxy_count()] == ["core.E002"]
    assert DeploySecurityChecks(debug=False, proxy_count_explicit=True).proxy_count() == []
    assert DeploySecurityChecks(debug=True, proxy_count_explicit=False).proxy_count() == []
