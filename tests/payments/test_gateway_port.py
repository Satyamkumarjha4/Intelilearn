"""Unit under test: `payments.gateway` (the port and its value objects), `payments.registry.PaymentGateways`,
`payments.config.GatewayConfig`, `payments.fake.FakeGateway` and the `payments.checks` system check (credits plan §6.4,
T25, T26).

Why: every provider is one subclass of the port, so what the port promises (a refund is not offered unless declared, a
checkout says how the browser pays, a key never shows in a log) is what the app can rely on. The registry is what stops
a client naming a provider that is off, and the fake gateway must not exist anywhere but the throwaway test stack. A
missing key must be an error when the app starts, not at the first sale.

Use cases:
- the port cannot be instantiated without its three abstract methods; a refund is `NotSupported` unless the gateway
  declares the capability; `can_refund` follows the declaration
- a checkout session says `redirect` with a link or `client` with an adapter and its parameters (never a secret), and
  the value objects are frozen
- `GatewayConfig` shows the names of its values and never the values, and says which required ones are blank
- the registry lists the enabled gateways in the environment's order, skips ones that are unknown, picks the default
  (else the first, else none), and refuses a key that is not enabled or none at all with nothing on
- the fake gateway is known only where `PAYMENT_ALLOW_FAKE_GATEWAY` is true
- the fake gateway: a redirect checkout back to the site, a signed body read into an event, a bad or missing signature,
  a body it cannot read and an event kind it does not know refused, a refund it can make, `pending` for any status
- the system check: nothing enabled is fine; an unknown name, an enabled gateway without its key, and the fake gateway
  without its switch are each an error with its own id
"""

import dataclasses
import json
from datetime import UTC, datetime

import pytest

from payments.checks import payment_gateways_are_configured
from payments.config import GatewayConfig
from payments.errors import GatewayNotEnabled, InvalidWebhook, NotSupported
from payments.fake import FakeGateway
from payments.gateway import CheckoutOrder, CheckoutSession, PaymentEvent, PaymentGateway, PaymentStatus, ReturnUrls
from payments.registry import PaymentGateways

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
ORDER = CheckoutOrder("o1", 5000, "INR", "Weekly Pro", "a@example.com")
URLS = ReturnUrls("http://s/ok", "http://s/no")


class Minimal(PaymentGateway):
    key, display_name = "minimal", "Minimal"

    def create_checkout(self, order, urls):
        return CheckoutSession(CheckoutSession.REDIRECT, "r", urls.success)

    def verify_webhook(self, headers, raw_body):
        return []

    def fetch_status(self, provider_ref):
        return PaymentStatus(PaymentStatus.PENDING)


class Refunding(Minimal):
    key = "refunding"
    capabilities = frozenset({PaymentGateway.REFUND})


class TestThePort:
    def test_it_cannot_be_used_without_its_three_methods(self):
        class Half(PaymentGateway):
            key, display_name = "half", "Half"

        with pytest.raises(TypeError):
            Half()

    def test_a_refund_is_not_offered_unless_declared(self):
        assert not Minimal().can_refund and Refunding().can_refund
        with pytest.raises(NotSupported):
            Minimal().refund("pay_1", 100)

    def test_a_redirect_and_a_client_session_say_how_to_pay(self):
        redirect = CheckoutSession(CheckoutSession.REDIRECT, "r1", "http://p/pay")
        client = CheckoutSession(CheckoutSession.CLIENT, "r2", adapter="razorpay", client={"order_id": "o"})

        assert redirect.as_json() == {"kind": "redirect", "redirect_url": "http://p/pay"}
        assert client.as_json() == {"kind": "client", "adapter": "razorpay", "client": {"order_id": "o"}}

    def test_the_value_objects_are_frozen(self):
        for value in (ORDER, URLS, CheckoutSession("redirect", "r"), PaymentStatus("paid")):
            with pytest.raises(dataclasses.FrozenInstanceError):
                value.amount_paise = 1

    def test_the_event_kinds_are_the_four(self):
        assert PaymentEvent.KINDS == ("succeeded", "failed", "refunded", "disputed")


class TestTheConfig:
    def test_it_shows_names_and_not_values(self):
        config = GatewayConfig({"secret_key": "sk_live_hunter2", "webhook_secret": "whsec_abc"})

        assert "hunter2" not in repr(config) and "whsec_abc" not in repr(config)
        assert "secret_key" in repr(config) and config.get("secret_key") == "sk_live_hunter2"

    def test_it_says_which_required_values_are_blank(self):
        config = GatewayConfig({"a": "x", "b": "  ", "c": ""})

        assert config.missing(("a", "b", "c", "d")) == ["b", "c", "d"]

    def test_it_reads_from_the_settings(self, settings):
        settings.STRIPE_SECRET_KEY = "sk_test_1"

        assert GatewayConfig.from_settings({"secret": "STRIPE_SECRET_KEY", "x": "NOT_A_SETTING"}).values == {
            "secret": "sk_test_1", "x": "",
        }  # fmt: skip


class TestTheRegistry:
    def make(self, enabled, default="a"):
        classes = {
            "a": type("A", (Minimal,), {"key": "a", "display_name": "A"}),
            "b": type("B", (Minimal,), {"key": "b", "display_name": "B"}),
        }
        return PaymentGateways(classes=classes, enabled=lambda: enabled, default=lambda: default)

    def test_enabled_lists_them_in_the_environments_order_and_skips_unknown_ones(self):
        assert [g.key for g in self.make(["b", "zzz", "a", "b"]).enabled()] == ["b", "a"]

    def test_the_default_is_the_named_one_else_the_first_else_none(self):
        assert self.make(["b", "a"], default="a").default().key == "a"
        assert self.make(["b", "a"], default="stripe").default().key == "b"
        assert self.make([]).default() is None

    def test_a_key_that_is_not_enabled_is_refused(self):
        registry = self.make(["a"])

        assert registry.for_key("a").key == "a"
        with pytest.raises(GatewayNotEnabled):
            registry.for_key("b")

    def test_no_key_means_the_default_and_with_none_on_buying_is_closed(self):
        assert self.make(["b"]).for_key(None).key == "b"
        with pytest.raises(GatewayNotEnabled):
            self.make([]).for_key("")

    def test_lookup_finds_a_gateway_that_was_switched_off_since(self):
        assert self.make([]).lookup("a").key == "a" and self.make([]).lookup("zzz") is None

    def test_the_fake_gateway_exists_only_where_it_is_allowed(self, settings):
        registry = PaymentGateways(enabled=lambda: ["fake"])
        settings.PAYMENT_ALLOW_FAKE_GATEWAY = False
        assert registry.enabled() == [] and not registry.known("fake")
        settings.PAYMENT_ALLOW_FAKE_GATEWAY = True
        assert [g.key for g in registry.enabled()] == ["fake"] and registry.known("fake")

    def test_configured_lists_what_the_environment_names_once(self):
        assert self.make(["a", "x", "a"]).configured() == ["a", "x"]


@pytest.fixture
def fake(settings):
    settings.PAYMENT_ALLOW_FAKE_GATEWAY = True
    settings.PAYMENT_FAKE_GATEWAY_SECRET = "s3cret"
    return FakeGateway.from_settings()


def event_body(**over):
    data = {"id": "e1", "type": "succeeded", "provider_ref": "fake_o1", "payment_ref": "p1", "amount_paise": 5000,
            "currency": "INR", "occurred_at": NOW.isoformat(), **over}  # fmt: skip
    return json.dumps(data).encode()


class TestTheFakeGateway:
    def test_its_checkout_goes_straight_back_to_the_site(self, fake):
        session = fake.create_checkout(ORDER, URLS)

        assert (session.kind, session.provider_ref, session.redirect_url) == ("redirect", "fake_o1", "http://s/ok")

    def test_a_signed_body_is_read_into_an_event(self, fake):
        body = event_body()

        [event] = fake.verify_webhook({"x-fake-signature": FakeGateway.sign("s3cret", body)}, body)

        assert event == PaymentEvent("e1", "succeeded", "fake_o1", 5000, "INR", NOW, "p1")

    @pytest.mark.parametrize("headers", [{}, {"X-Fake-Signature": "0" * 64}, {"X-Fake-Signature": ""}])
    def test_a_missing_or_wrong_signature_is_refused(self, fake, headers):
        with pytest.raises(InvalidWebhook):
            fake.verify_webhook(headers, event_body())

    def test_a_body_signed_with_another_secret_or_altered_after_signing_is_refused(self, fake):
        body = event_body()
        with pytest.raises(InvalidWebhook):
            fake.verify_webhook({"X-Fake-Signature": FakeGateway.sign("other", body)}, body)
        with pytest.raises(InvalidWebhook):
            fake.verify_webhook({"X-Fake-Signature": FakeGateway.sign("s3cret", body)}, body.replace(b"5000", b"9999"))

    @pytest.mark.parametrize("body", [b"not json", b"[]", event_body(type="exploded"), event_body(amount_paise="lots")])
    def test_a_signed_body_that_cannot_be_read_is_refused(self, fake, body):
        with pytest.raises(InvalidWebhook):
            fake.verify_webhook({"X-Fake-Signature": FakeGateway.sign("s3cret", body)}, body)

    def test_it_can_refund_and_has_nothing_to_ask_about_a_payment(self, fake):
        assert fake.can_refund and fake.refund("p1", 700).amount_paise == 700
        assert fake.fetch_status("fake_o1").state == "pending"


class TestTheSystemCheck:
    def test_nothing_enabled_is_fine(self, settings):
        settings.PAYMENT_GATEWAYS_ENABLED = []

        assert payment_gateways_are_configured(None) == []

    def test_a_name_that_is_not_a_gateway_is_an_error(self, settings):
        settings.PAYMENT_GATEWAYS_ENABLED = ["paypal"]

        assert [e.id for e in payment_gateways_are_configured(None)] == ["payments.E001"]

    def test_an_enabled_gateway_without_its_key_is_an_error(self, settings):
        settings.PAYMENT_GATEWAYS_ENABLED = ["fake"]
        settings.PAYMENT_ALLOW_FAKE_GATEWAY = True
        settings.PAYMENT_FAKE_GATEWAY_SECRET = ""

        [error] = payment_gateways_are_configured(None)
        assert error.id == "payments.E002" and "webhook_secret" in error.msg

    def test_the_fake_gateway_without_its_switch_is_an_error(self, settings):
        settings.PAYMENT_GATEWAYS_ENABLED = ["fake"]
        settings.PAYMENT_ALLOW_FAKE_GATEWAY = False

        assert [e.id for e in payment_gateways_are_configured(None)] == ["payments.E003"]

    def test_a_properly_set_up_gateway_passes(self, settings):
        settings.PAYMENT_GATEWAYS_ENABLED = ["fake"]
        settings.PAYMENT_ALLOW_FAKE_GATEWAY = True
        settings.PAYMENT_FAKE_GATEWAY_SECRET = "s3cret"

        assert payment_gateways_are_configured(None) == []
