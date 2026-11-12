"""Email delivery for sign-in (phase 11): a `Mailer` port, a registry of backends chosen by `MAIL_BACKEND`, and a
task that
sends. Importing the package registers the backends and the system checks."""

from . import brevo, checks, console, outbox  # noqa: F401,E402  (each registers itself)
from .registry import MailBackends, UnknownMailBackend  # noqa: F401  (first: the backends register on it)
