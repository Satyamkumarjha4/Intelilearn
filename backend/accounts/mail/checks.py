"""System checks that keep a development mail backend out of production (`accounts.E001` to `E004`; the shape of
the fake
payment gateway's `payments.E003` and `E004`).

The console backend prints a code to a log, and the outbox keeps it where a test endpoint can read it: either, in
production,
would hand a sign-up code to whoever reads the log or hits the endpoint. A mail setting that names nothing real
must stop the
app when it starts, not at the first sign-up.
"""

from django.core.checks import Error, Tags, register

from .registry import MailBackends


class MailSafety:
    def __init__(self, backend=None, debug=None, allow_outbox=None, classes=None):
        self._backend, self._debug, self._allow_outbox, self._classes = backend, debug, allow_outbox, classes

    @property
    def backend(self) -> str:
        from django.conf import settings

        return self._backend if self._backend is not None else settings.MAIL_BACKEND

    @property
    def debug(self) -> bool:
        from django.conf import settings

        return self._debug if self._debug is not None else settings.DEBUG

    @property
    def allow_outbox(self) -> bool:
        from django.conf import settings

        return self._allow_outbox if self._allow_outbox is not None else bool(settings.MAIL_ALLOW_OUTBOX)

    @property
    def classes(self):
        return self._classes if self._classes is not None else MailBackends.REGISTERED

    def deploy_errors(self) -> list[Error]:
        """For `check --deploy`: the development backend in a deployment."""
        if self.backend == "console" and not self.debug:
            return [
                Error(
                    "MAIL_BACKEND is console while DJANGO_DEBUG is false.",
                    hint="The console backend prints sign-up codes to the log. Set MAIL_BACKEND to a real backend "
                    "(brevo) and its settings (see .env.example).",
                    id="accounts.E001",
                )
            ]
        return []

    def errors(self) -> list[Error]:
        found: list[Error] = []
        if self.backend == "outbox" and not self.allow_outbox:
            found.append(
                Error(
                    "MAIL_BACKEND is outbox but MAIL_ALLOW_OUTBOX is not true.",
                    hint="The outbox exists only on the throwaway test stack: set MAIL_ALLOW_OUTBOX=true there, "
                    "or use another backend.",
                    id="accounts.E002",
                )
            )
        if self.allow_outbox and not self.debug:
            found.append(
                Error(
                    "MAIL_ALLOW_OUTBOX is true while DJANGO_DEBUG is false.",
                    hint="The outbox lets a test read sign-up codes. Remove MAIL_ALLOW_OUTBOX from this environment.",
                    id="accounts.E003",
                )
            )
        if self.backend not in self.classes:
            found.append(
                Error(
                    f"MAIL_BACKEND names '{self.backend}', which is not a mail backend.",
                    hint=f"Known backends: {', '.join(sorted(self.classes)) or 'none'}.",
                    id="accounts.E004",
                )
            )
        else:
            missing = self.classes[self.backend].from_settings().missing_config()
            if missing:
                found.append(
                    Error(
                        f"The mail backend '{self.backend}' is selected but {', '.join(missing)} is not set.",
                        hint="Set it in the environment (see .env.example), or choose another MAIL_BACKEND.",
                        id="accounts.E004",
                    )
                )
        return found


@register(Tags.security, deploy=False)
def mail_backend_is_usable(app_configs=None, **kwargs):
    return MailSafety().errors()


@register(Tags.security, deploy=True)
def mail_backend_is_fit_for_production(app_configs=None, **kwargs):
    return MailSafety().deploy_errors()
