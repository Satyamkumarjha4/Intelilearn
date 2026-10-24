from core.checks import secret_key_check


def test_development_secret_key_fails_the_deploy_check(settings):
    settings.SECRET_KEY = settings.DEV_SECRET_KEY
    assert [e.id for e in secret_key_check()] == ["core.E001"]


def test_real_secret_key_passes(settings):
    settings.SECRET_KEY = "a-long-random-production-value-" + "x" * 30
    assert secret_key_check() == []
