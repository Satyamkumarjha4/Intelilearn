"""The port every payment provider implements (credits plan §6.4).

Adding a provider is one subclass of `PaymentGateway`, one line in the registry and its settings: nothing that takes an
order, hears a webhook or grants credits knows which provider it is talking to. The value objects are frozen, so what a
gateway hands back cannot be changed by whoever receives it.
"""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar

from .config import GatewayConfig
from .errors import NotSupported


@dataclass(frozen=True)
class CheckoutOrder:
    """What a gateway needs to start a checkout. The amount is the server's (from the plan table), in paise."""

    order_id: str
    amount_paise: int
    currency: str
    description: str
    buyer_email: str = ""


@dataclass(frozen=True)
class ReturnUrls:
    success: str
    cancel: str


@dataclass(frozen=True)
class CheckoutSession:
    """How the browser pays: `redirect` (go to `redirect_url`) or `client` (the provider's own on-page checkout, which
    the frontend opens with `client`, non-secret parameters, using the adapter named in `adapter`)."""

    kind: str
    provider_ref: str
    redirect_url: str = ""
    client: Mapping[str, object] = field(default_factory=dict)
    adapter: str = ""
    expires_at: datetime | None = None

    REDIRECT = "redirect"
    CLIENT = "client"

    def as_json(self) -> dict:
        if self.kind == self.REDIRECT:
            return {"kind": self.kind, "redirect_url": self.redirect_url}
        return {"kind": self.kind, "adapter": self.adapter, "client": dict(self.client)}


@dataclass(frozen=True)
class PaymentEvent:
    """One thing the provider says happened, in our words. Only these fields are kept (never the raw body)."""

    event_id: str
    kind: str  # succeeded, failed, refunded or disputed
    provider_ref: str
    amount_paise: int
    currency: str
    occurred_at: datetime
    payment_ref: str = ""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REFUNDED = "refunded"
    DISPUTED = "disputed"
    KINDS = (SUCCEEDED, FAILED, REFUNDED, DISPUTED)


@dataclass(frozen=True)
class PaymentStatus:
    """What the provider says about one payment when asked."""

    state: str  # pending, paid, failed or expired
    amount_paise: int = 0
    currency: str = "INR"
    payment_ref: str = ""

    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    EXPIRED = "expired"


@dataclass(frozen=True)
class RefundResult:
    refund_ref: str
    amount_paise: int


class PaymentGateway(ABC):
    """One payment provider."""

    key: ClassVar[str]
    display_name: ClassVar[str]
    supported_currencies: ClassVar[tuple[str, ...]] = ("INR",)
    capabilities: ClassVar[frozenset[str]] = frozenset()
    #: the config values that must be set for this gateway to be switched on
    required_config: ClassVar[tuple[str, ...]] = ()

    REFUND = "refund"

    def __init__(self, config: GatewayConfig | None = None):
        self.config = config or GatewayConfig()

    @classmethod
    def config_names(cls) -> dict[str, str]:
        """The config values and the Django setting each comes from."""
        return {}

    @classmethod
    def from_settings(cls) -> "PaymentGateway":
        return cls(GatewayConfig.from_settings(cls.config_names()))

    def missing_config(self) -> list[str]:
        return self.config.missing(self.required_config)

    @abstractmethod
    def create_checkout(self, order: CheckoutOrder, urls: ReturnUrls) -> CheckoutSession:
        """Start a payment for `order`. Raises `GatewayUnavailable` when the provider cannot be reached."""

    @abstractmethod
    def verify_webhook(self, headers: Mapping[str, str], raw_body: bytes) -> list[PaymentEvent]:
        """The events in a callback, once its signature is proved. Pure: no database. Raises `InvalidWebhook`."""

    @abstractmethod
    def fetch_status(self, provider_ref: str) -> PaymentStatus:
        """Ask the provider about a payment, for a webhook that was late or lost."""

    def refund(self, payment_ref: str, amount_paise: int) -> RefundResult:
        """Refund through the provider. Only a gateway that declares the capability does."""
        raise NotSupported(f"{self.display_name} cannot refund from here.")

    @property
    def can_refund(self) -> bool:
        return self.REFUND in self.capabilities
