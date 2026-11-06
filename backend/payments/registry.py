"""Which gateways exist and which are switched on (T25): `PAYMENT_GATEWAYS_ENABLED` and `PAYMENT_DEFAULT_GATEWAY`."""

from collections.abc import Callable

from django.conf import settings

from .errors import GatewayNotEnabled
from .gateway import PaymentGateway


class PaymentGateways:
    """The registry. `register` adds a class (the adapter modules do it when they are loaded); `enabled` is what the
    environment switches on, in order; `for_key` refuses a gateway that is not enabled, whatever a client asked for. A
    test hands in its own classes and lists, so nothing global changes."""

    REGISTERED: dict[str, type[PaymentGateway]] = {}
    FAKE_KEY = "fake"

    def __init__(
        self,
        classes: dict[str, type[PaymentGateway]] | None = None,
        enabled: Callable[[], list[str]] | None = None,
        default: Callable[[], str] | None = None,
    ):
        self._classes = classes
        self._enabled = enabled or (lambda: list(settings.PAYMENT_GATEWAYS_ENABLED))
        self._default = default or (lambda: settings.PAYMENT_DEFAULT_GATEWAY)

    @classmethod
    def register(cls, gateway: type[PaymentGateway]) -> type[PaymentGateway]:
        """Usable as a class decorator."""
        cls.REGISTERED[gateway.key] = gateway
        return gateway

    @property
    def classes(self) -> dict[str, type[PaymentGateway]]:
        return self.REGISTERED if self._classes is None else self._classes

    def known(self, key: str) -> bool:
        """Registered, and (for the fake one) allowed to exist at all."""
        if key not in self.classes:
            return False
        return key != self.FAKE_KEY or bool(settings.PAYMENT_ALLOW_FAKE_GATEWAY)

    def enabled(self) -> list[PaymentGateway]:
        """The switched-on gateways, in the order the environment lists them."""
        keys = dict.fromkeys(self._enabled())
        return [self.classes[key].from_settings() for key in keys if self.known(key)]

    def default(self) -> PaymentGateway | None:
        """The default gateway when it is on, else the first that is, else none (buying is closed)."""
        gateways = self.enabled()
        wanted = self._default()
        return next((g for g in gateways if g.key == wanted), gateways[0] if gateways else None)

    def for_key(self, key: str | None) -> PaymentGateway:
        """The gateway a client named (or the default for none), only if it is enabled."""
        if not key:
            gateway = self.default()
            if gateway is None:
                raise GatewayNotEnabled("Buying isn't open yet.")
            return gateway
        found = next((g for g in self.enabled() if g.key == key), None)
        if found is None:
            raise GatewayNotEnabled()
        return found

    def lookup(self, key: str) -> PaymentGateway | None:
        """A gateway that exists, enabled or not: an order made before it was switched off still has to be settled."""
        return self.classes[key].from_settings() if self.known(key) else None

    def configured(self) -> list[str]:
        """Every key the environment lists, known or not (for the system check)."""
        return list(dict.fromkeys(self._enabled()))
