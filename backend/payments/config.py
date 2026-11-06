"""The keys of one gateway, read from the environment through Django's settings."""

from dataclasses import dataclass, field

from django.conf import settings


@dataclass(frozen=True)
class GatewayConfig:
    """Named values of one gateway (`secret_key`, `webhook_secret`…). Never logged: the `repr` shows the names and not
    the values, so a stray `print` or a traceback cannot leak a key."""

    values: dict[str, str] = field(default_factory=dict)

    def get(self, name: str) -> str:
        return self.values.get(name, "")

    def missing(self, required: tuple[str, ...]) -> list[str]:
        return [name for name in required if not self.get(name).strip()]

    def __repr__(self) -> str:
        return f"GatewayConfig({', '.join(sorted(self.values))})"

    @classmethod
    def from_settings(cls, mapping: dict[str, str]) -> "GatewayConfig":
        """`mapping` names the config values and the Django setting each is read from."""
        return cls({name: str(getattr(settings, setting, "") or "") for name, setting in mapping.items()})
