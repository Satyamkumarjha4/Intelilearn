"""System checks that keep the stand-in provider out of production and a half-set-up provider from starting
(`accounts.E005` to `E008`; the shape of `accounts.E001` to `E004` for mail and `payments.E003`, `E004` for the fake
gateway).

The fake provider answers the sign-in redirect with whatever identity a request names: on a public site that would let
anyone sign in as anyone. So it needs its own switch, and the switch is refused unless `DJANGO_DEBUG` is on."""

from django.core.checks import Error, Tags, register

from .registry import IdentityProviders


class ProviderSafety:
    def __init__(self, enabled=None, allow_fake=None, debug=None, classes=None):
        self._enabled, self._allow_fake, self._debug, self._classes = enabled, allow_fake, debug, classes

    @property
    def enabled(self) -> list[str]:
        from django.conf import settings

        return list(self._enabled if self._enabled is not None else settings.AUTH_PROVIDERS_ENABLED)

    @property
    def allow_fake(self) -> bool:
        from django.conf import settings

        return bool(self._allow_fake if self._allow_fake is not None else settings.AUTH_ALLOW_FAKE_PROVIDER)

    @property
    def debug(self) -> bool:
        from django.conf import settings

        return bool(self._debug if self._debug is not None else settings.DEBUG)

    @property
    def classes(self):
        return self._classes if self._classes is not None else IdentityProviders.REGISTERED

    def errors(self) -> list[Error]:
        found: list[Error] = []
        if self.allow_fake and not self.debug:
            found.append(
                Error(
                    "AUTH_ALLOW_FAKE_PROVIDER is on while DJANGO_DEBUG is off.",
                    hint="The fake sign-in provider lets a request name who is signing in. It exists for the "
                    "throwaway test stack only; turn AUTH_ALLOW_FAKE_PROVIDER off.",
                    id="accounts.E006",
                )
            )
        if "fake" in self.enabled and not self.allow_fake:
            found.append(
                Error(
                    "AUTH_PROVIDERS_ENABLED names the fake provider but AUTH_ALLOW_FAKE_PROVIDER is off.",
                    hint="Remove `fake` from AUTH_PROVIDERS_ENABLED, or (on the throwaway test stack only) turn the "
                    "switch on.",
                    id="accounts.E005",
                )
            )
        for key in self.enabled:
            if key not in self.classes:
                found.append(
                    Error(
                        f"AUTH_PROVIDERS_ENABLED names {key!r}, which is not a known provider.",
                        hint=f"Known providers: {', '.join(sorted(self.classes))}.",
                        id="accounts.E007",
                    )
                )
                continue
            missing = self.classes[key].from_settings().missing_config()
            if missing:
                found.append(
                    Error(
                        f"The {key} provider is on but {', '.join(missing)} {'is' if len(missing) == 1 else 'are'} "
                        "not set.",
                        hint="Set them in the environment (see .env.example) or take the provider out of "
                        "AUTH_PROVIDERS_ENABLED.",
                        id="accounts.E008",
                    )
                )
        return found


@register(Tags.security)
def provider_safety_check(app_configs=None, **kwargs):
    return ProviderSafety().errors()
