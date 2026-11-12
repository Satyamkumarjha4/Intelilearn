"""Unit under test: the credits and payments settings in `config/settings.py` and `config/celery.py` that no other test
reads: the payment return URL, the fake-gateway switch, the throttle rates and the beat schedule.

Why: these are the names the credits and payments code reads at start. A mistyped one fails in production, not in a
test, and a throttle or a schedule that silently changes is a change to what is limited or run, with no failing test.

Use cases:
- the return base URL is a web address with no trailing slash
- the fake gateway is off by default
- the four credits and payments throttle scopes have their planned rates
- the beat schedule runs `credits.tick` every hour, `payments.reconcile` every five minutes and the sign-in housekeeping
  (`accounts.purge`) once a day, and nothing else
"""

import pytest
from django.conf import settings

from config.celery import app as celery_app


class TestPaymentSettings:
    def test_the_return_base_url_is_a_web_address_without_a_trailing_slash(self):
        assert settings.PAYMENT_RETURN_BASE_URL.startswith(("http://", "https://"))
        assert not settings.PAYMENT_RETURN_BASE_URL.endswith("/")

    def test_the_fake_gateway_is_off_by_default(self):
        assert settings.PAYMENT_ALLOW_FAKE_GATEWAY is False


@pytest.mark.parametrize(
    ("scope", "rate"),
    [
        ("credits_quote", "120/min"),
        ("payment_order", "10/hour"),
        ("payment_status", "60/min"),
        ("payment_webhook", "600/min"),
    ],
)
def test_the_new_throttle_scopes_have_their_planned_rates(scope, rate):
    assert settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"][scope] == rate


def test_the_beat_schedule_runs_the_credits_tick_hourly_the_payments_job_every_five_minutes_and_the_purge_daily():
    expected = {
        "credits.tick": {"task": "credits.tick", "schedule": 3600.0},
        "payments.reconcile": {"task": "payments.reconcile", "schedule": 300.0},
        "accounts.purge": {"task": "accounts.purge", "schedule": 86400.0},
    }

    assert settings.CELERY_BEAT_SCHEDULE == expected
    assert celery_app.conf.beat_schedule == expected
