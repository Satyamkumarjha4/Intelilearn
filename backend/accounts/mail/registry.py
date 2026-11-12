"""Which mail backends exist and which one is used: `MAIL_BACKEND` (phase 11, D2; the pattern of `PaymentGateways`)."""

from django.conf import settings

from .mailer import Mailer


class UnknownMailBackend(Exception):
    pass


class MailBackends:
    """`register` adds a class (each backend module does it when it is loaded); `current` builds the one
    `MAIL_BACKEND` names.
    A test hands in its own classes, so nothing global changes."""

    REGISTERED: dict[str, type[Mailer]] = {}

    def __init__(self, classes: dict[str, type[Mailer]] | None = None):
        self._classes = classes

    @classmethod
    def register(cls, mailer: type[Mailer]) -> type[Mailer]:
        """Usable as a class decorator."""
        cls.REGISTERED[mailer.key] = mailer
        return mailer

    @property
    def classes(self) -> dict[str, type[Mailer]]:
        return self.REGISTERED if self._classes is None else self._classes

    def current(self) -> Mailer:
        key = settings.MAIL_BACKEND
        if key not in self.classes:
            raise UnknownMailBackend(
                f"MAIL_BACKEND is {key!r}; the known backends are {', '.join(sorted(self.classes))}."
            )
        return self.classes[key].from_settings()
