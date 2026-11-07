"""The system check that makes a payment misconfiguration show when the app starts (T25), not at the first sale."""

from dataclasses import dataclass

from django.core.checks import Error, register
from django.core.checks import Tags as DjangoTags

from .registry import PaymentGateways


@register(DjangoTags.security, deploy=False)
def payment_gateways_are_configured(app_configs, **kwargs):
    """Every gateway named in `PAYMENT_GATEWAYS_ENABLED` exists and has its keys; the fake one needs its switch."""
    from django.conf import settings

    gateways = PaymentGateways()
    errors = []
    for key in gateways.configured():
        if key == PaymentGateways.FAKE_KEY and not settings.PAYMENT_ALLOW_FAKE_GATEWAY:
            errors.append(
                Error(
                    "The fake payment gateway is enabled but not allowed.",
                    hint="It exists only on the throwaway test stack: set PAYMENT_ALLOW_FAKE_GATEWAY=true there, "
                    "or remove it.",
                    id="payments.E003",
                )
            )
        elif key not in gateways.classes:
            errors.append(
                Error(
                    f"PAYMENT_GATEWAYS_ENABLED names '{key}', which is not a payment gateway.",
                    hint=f"Known gateways: {', '.join(sorted(gateways.classes)) or 'none'}.",
                    id="payments.E001",
                )
            )
        else:
            missing = gateways.classes[key].from_settings().missing_config()
            if missing:
                errors.append(
                    Error(
                        f"The payment gateway '{key}' is enabled but {', '.join(missing)} is not set.",
                        hint="Set it in the environment (see .env.example), "
                        "or take the gateway out of PAYMENT_GATEWAYS_ENABLED.",
                        id="payments.E002",
                    )
                )
    return errors


@dataclass(frozen=True)
class LiveKey:
    """A setting that holds a provider key, and the prefixes that mark one as a live-mode key."""

    setting: str
    prefixes: tuple[str, ...]


class PaymentSafety:
    """The two start-up refusals that keep real money and a fake gateway apart (phase 10.7).

    A live key in a development `.env` charges real cards; the fake gateway in production lets anyone who holds its
    signing secret grant credits. Neither message prints a key, only the name of the setting. Razorpay's key id is
    listed here already, so the Razorpay adapter inherits the check. A webhook secret is not listed: Stripe's carry no
    mode marker (`whsec_` for both), so the key that sits beside it is what tells the modes apart.
    """

    LIVE_KEYS = (
        LiveKey("STRIPE_SECRET_KEY", ("sk_live_", "rk_live_")),
        LiveKey("STRIPE_PUBLISHABLE_KEY", ("pk_live_",)),
        LiveKey("RAZORPAY_KEY_ID", ("rzp_live_",)),
    )

    def errors(self) -> list[Error]:
        return [*self.fake_gateway_in_production(), *self.live_keys_without_the_switch()]

    def fake_gateway_in_production(self) -> list[Error]:
        from django.conf import settings

        if not (settings.PAYMENT_ALLOW_FAKE_GATEWAY and not settings.DEBUG):
            return []
        return [
            Error(
                "PAYMENT_ALLOW_FAKE_GATEWAY is true while DJANGO_DEBUG is false.",
                hint="The fake gateway exists only on the throwaway test stack, which runs with DJANGO_DEBUG=true. "
                "Remove PAYMENT_ALLOW_FAKE_GATEWAY from this environment.",
                id="payments.E004",
            )
        ]

    def live_keys_without_the_switch(self) -> list[Error]:
        from django.conf import settings

        if settings.PAYMENTS_LIVE_MODE:
            return []
        return [
            Error(
                f"{key.setting} holds a live-mode key but PAYMENTS_LIVE_MODE is not true.",
                hint="Use test keys while developing. On the production host, set PAYMENTS_LIVE_MODE=true "
                "on purpose to accept real payments.",
                id="payments.E005",
            )
            for key in self.LIVE_KEYS
            if str(getattr(settings, key.setting, "") or "").strip().startswith(key.prefixes)
        ]


@register(DjangoTags.security, deploy=False)
def payments_are_safe(app_configs, **kwargs):
    return PaymentSafety().errors()
