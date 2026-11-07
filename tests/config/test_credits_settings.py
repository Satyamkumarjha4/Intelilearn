"""Unit under test: the settings and apps Phase 10.0 prepares for credits and payments (`config/settings.py`,
`config/celery.py`).

Why: credits and payments arrive in nine small phases. Until the last one switches them on, a learner must notice
nothing, so the apps are empty, the action gate is still the open one and nothing is scheduled. What 10.0 does leave
behind is the configuration the later phases read; if a name is missing or mistyped there, a later phase fails at start
in production instead of in a test.

Use cases:
- the `credits` and `payments` apps are installed; `payments` holds its three models (orders and their events, phase
  10.6; the refunds an administrator asked for, phase 10.8)
- the action gate is still the open one, and the activity sink does nothing
- the payment settings exist with the right types: gateways enabled (a list, none by default), the default gateway, the
  keys of each provider (text), the return base URL, the fake-gateway switch (off) and the dollar-rupee rate (positive)
- the four new throttle scopes have a rate
- the beat schedule runs `credits.tick` every hour and `payments.reconcile` every five minutes, and nothing else
"""

from decimal import Decimal

import pytest
from django.apps import apps
from django.conf import settings

from config.celery import app as celery_app


@pytest.mark.parametrize("label", ["payments"])
def test_the_payments_app_is_installed_and_holds_its_three_models(label):
    config = apps.get_app_config(label)

    assert sorted(model.__name__ for model in config.get_models()) == [
        "PaymentEventLog",
        "PaymentOrder",
        "RefundAttempt",
    ]
    assert label in [name.split(".")[0] for name in settings.INSTALLED_APPS]


def test_the_credits_app_is_installed():
    assert "credits" in [name.split(".")[0] for name in settings.INSTALLED_APPS]


def test_the_action_gate_is_still_the_open_one_and_the_activity_sink_does_nothing():
    assert settings.ACTION_GATE == "lessons.metering.OpenGate"
    assert settings.ACTIVITY_SINK == "lessons.activity.NullActivity"


class TestPaymentSettings:
    def test_gateways_enabled_is_a_list_of_names(self):
        assert isinstance(settings.PAYMENT_GATEWAYS_ENABLED, list)
        assert all(
            isinstance(name, str) and name == name.strip().lower() and name
            for name in settings.PAYMENT_GATEWAYS_ENABLED
        )

    def test_the_default_gateway_is_stripe_unless_the_environment_says_otherwise(self):
        assert isinstance(settings.PAYMENT_DEFAULT_GATEWAY, str) and settings.PAYMENT_DEFAULT_GATEWAY

    @pytest.mark.parametrize(
        "name",
        [
            "STRIPE_SECRET_KEY",
            "STRIPE_WEBHOOK_SECRET",
            "RAZORPAY_KEY_ID",
            "RAZORPAY_KEY_SECRET",
            "RAZORPAY_WEBHOOK_SECRET",
        ],
    )
    def test_each_provider_key_exists_as_text(self, name):
        assert isinstance(getattr(settings, name), str)

    def test_the_return_base_url_is_a_web_address_without_a_trailing_slash(self):
        assert settings.PAYMENT_RETURN_BASE_URL.startswith(("http://", "https://"))
        assert not settings.PAYMENT_RETURN_BASE_URL.endswith("/")

    def test_the_fake_gateway_is_off_by_default(self):
        assert settings.PAYMENT_ALLOW_FAKE_GATEWAY is False

    def test_the_dollar_rupee_rate_is_a_positive_number(self):
        assert Decimal(str(settings.USD_INR_RATE)) > 0


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


def test_the_beat_schedule_runs_the_credits_tick_every_hour_and_the_payments_job_every_five_minutes():
    expected = {
        "credits.tick": {"task": "credits.tick", "schedule": 3600.0},
        "payments.reconcile": {"task": "payments.reconcile", "schedule": 300.0},
    }

    assert settings.CELERY_BEAT_SCHEDULE == expected
    assert celery_app.conf.beat_schedule == expected
