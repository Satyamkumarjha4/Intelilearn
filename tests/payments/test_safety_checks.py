"""Unit under test: `payments.checks.PaymentSafety`, the start-up checks that keep real money out of a development stack
and a fake gateway out of a real one (credits plan T25, D20; phase 10.7 step 0).

Why: the two mistakes that cost the most are the quietest. A live Stripe or Razorpay key left in a `.env` on a laptop
charges real cards while someone is testing; the fake gateway left switched on in production lets anyone with the
signing secret grant credits. Both must stop the app at start, with an error that names the setting and never prints the
key, and neither may need a code change to turn off deliberately (`PAYMENTS_LIVE_MODE=true` is that deliberate act).

Use cases:
- the fake gateway allowed while DEBUG is off is an error (`payments.E004`); allowed with DEBUG on, or not allowed, is
  not
- a live Stripe secret key, a live restricted key or a live publishable key is an error (`payments.E005`) unless
  `PAYMENTS_LIVE_MODE` is true; test keys and blank keys are fine
- a live Razorpay key id is the same error and the same switch
- the error names the setting and never contains the key, and each live key is its own error
- the checks are registered with Django, so `manage.py check` and the server's start-up run them
"""

import pytest
from django.core import checks

from payments.checks import PaymentSafety

LIVE_SECRET = "sk_live_" + "x" * 24  # not a real key
TEST_SECRET = "sk_test_" + "x" * 24


def ids():
    return [error.id for error in PaymentSafety().errors()]


@pytest.fixture(autouse=True)
def clean(settings):
    """Start from a safe stack, whatever the host's `.env` holds."""
    settings.DEBUG = True
    settings.PAYMENT_ALLOW_FAKE_GATEWAY = False
    settings.PAYMENTS_LIVE_MODE = False
    settings.STRIPE_SECRET_KEY = settings.STRIPE_PUBLISHABLE_KEY = ""
    settings.RAZORPAY_KEY_ID = ""


class TestTheFakeGatewayStaysOnTheTestStack:
    def test_allowed_with_debug_off_is_an_error(self, settings):
        settings.PAYMENT_ALLOW_FAKE_GATEWAY, settings.DEBUG = True, False

        assert ids() == ["payments.E004"]

    def test_allowed_with_debug_on_is_fine(self, settings):
        settings.PAYMENT_ALLOW_FAKE_GATEWAY, settings.DEBUG = True, True

        assert ids() == []

    def test_not_allowed_is_fine_in_production(self, settings):
        settings.DEBUG = False

        assert ids() == []


class TestLiveKeysNeedTheLiveSwitch:
    @pytest.mark.parametrize(
        ("setting", "value"),
        [
            ("STRIPE_SECRET_KEY", LIVE_SECRET),
            ("STRIPE_SECRET_KEY", "rk_live_" + "x" * 24),
            ("STRIPE_PUBLISHABLE_KEY", "pk_live_" + "x" * 24),
            ("RAZORPAY_KEY_ID", "rzp_live_" + "x" * 14),
        ],
    )
    def test_a_live_key_is_an_error_without_the_switch(self, settings, setting, value):
        setattr(settings, setting, value)

        assert ids() == ["payments.E005"]

    @pytest.mark.parametrize(
        ("setting", "value"),
        [
            ("STRIPE_SECRET_KEY", LIVE_SECRET),
            ("STRIPE_PUBLISHABLE_KEY", "pk_live_" + "x" * 24),
            ("RAZORPAY_KEY_ID", "rzp_live_" + "x" * 14),
        ],
    )
    def test_the_switch_allows_it(self, settings, setting, value):
        setattr(settings, setting, value)
        settings.PAYMENTS_LIVE_MODE = True

        assert ids() == []

    @pytest.mark.parametrize(
        ("setting", "value"),
        [
            ("STRIPE_SECRET_KEY", TEST_SECRET),
            ("STRIPE_PUBLISHABLE_KEY", "pk_test_" + "x" * 24),
            ("RAZORPAY_KEY_ID", "rzp_test_" + "x" * 14),
            ("STRIPE_SECRET_KEY", ""),
        ],
    )
    def test_test_keys_and_blank_keys_are_fine(self, settings, setting, value):
        setattr(settings, setting, value)

        assert ids() == []

    def test_a_key_with_stray_spaces_or_a_newline_is_still_caught(self, settings):
        settings.STRIPE_SECRET_KEY = f"  {LIVE_SECRET}\n"

        assert ids() == ["payments.E005"]

    def test_the_error_names_the_setting_and_never_the_key(self, settings):
        settings.STRIPE_SECRET_KEY = LIVE_SECRET

        (error,) = PaymentSafety().errors()

        assert "STRIPE_SECRET_KEY" in error.msg and "PAYMENTS_LIVE_MODE" in (error.hint or error.msg)
        assert LIVE_SECRET not in f"{error.msg} {error.hint}" and "sk_live_x" not in f"{error.msg} {error.hint}"

    def test_each_live_key_is_its_own_error(self, settings):
        settings.STRIPE_SECRET_KEY, settings.RAZORPAY_KEY_ID = LIVE_SECRET, "rzp_live_" + "x" * 14

        assert ids() == ["payments.E005", "payments.E005"]

    def test_both_mistakes_together_are_both_reported(self, settings):
        settings.PAYMENT_ALLOW_FAKE_GATEWAY, settings.DEBUG = True, False
        settings.STRIPE_SECRET_KEY = LIVE_SECRET

        assert sorted(ids()) == ["payments.E004", "payments.E005"]


class TestRegisteredWithDjango:
    def test_manage_py_check_runs_them(self, settings):
        settings.PAYMENT_ALLOW_FAKE_GATEWAY, settings.DEBUG = True, False

        found = [
            error.id for error in checks.run_checks(tags=[checks.Tags.security]) if error.id.startswith("payments.")
        ]

        assert "payments.E004" in found
