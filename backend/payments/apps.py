from django.apps import AppConfig


class PaymentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "payments"

    def ready(self):
        from . import checks  # noqa: F401  (registers the system check)
        from .fake import FakeGateway
        from .registry import PaymentGateways
        from .stripe_gateway import StripeGateway

        PaymentGateways.register(FakeGateway)
        PaymentGateways.register(StripeGateway)
