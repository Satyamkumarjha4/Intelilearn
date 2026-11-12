"""Which sign-in providers exist and which are on: `AUTH_PROVIDERS_ENABLED` (the pattern of `PaymentGateways` and
`MailBackends`). A provider that is not on is the same as one that does not exist: no button, and its endpoints answer
`provider_off`."""

from django.conf import settings

from .provider import IdentityProvider


class IdentityProviders:
    REGISTERED: dict[str, type[IdentityProvider]] = {}

    def __init__(self, classes: dict[str, type[IdentityProvider]] | None = None, enabled: list[str] | None = None):
        self._classes, self._enabled = classes, enabled

    @classmethod
    def register(cls, provider: type[IdentityProvider]) -> type[IdentityProvider]:
        """Usable as a class decorator."""
        cls.REGISTERED[provider.key] = provider
        return provider

    @property
    def classes(self) -> dict[str, type[IdentityProvider]]:
        return self.REGISTERED if self._classes is None else self._classes

    @property
    def enabled_keys(self) -> list[str]:
        keys = settings.AUTH_PROVIDERS_ENABLED if self._enabled is None else self._enabled
        # The fake provider needs its own switch as well, and the switch itself is refused outside a debug run.
        return [key for key in keys if key in self.classes and (key != "fake" or settings.AUTH_ALLOW_FAKE_PROVIDER)]

    def enabled(self) -> list[IdentityProvider]:
        return [self.classes[key].from_settings() for key in self.enabled_keys]

    def get(self, key: str) -> IdentityProvider | None:
        """The provider called `key` if it is on, otherwise None."""
        return self.classes[key].from_settings() if key in self.enabled_keys else None
