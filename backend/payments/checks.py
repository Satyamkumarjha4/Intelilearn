"""The system check that makes a payment misconfiguration show when the app starts (T25), not at the first sale."""

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
