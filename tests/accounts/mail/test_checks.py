"""Unit under test: `accounts.mail.checks.MailSafety`, the system checks `accounts.E001` to `E004`.

Why: the development mail backends print a code or keep a readable outbox, which in production would hand a sign-up
code to
whoever reads a log or hits a test endpoint. The throwaway-stack switch must never be on outside a debug run, and a mail
setting that names nothing real must stop the app at start, not at the first sign-up. (The same shape as the fake
payment
gateway's checks, `payments.E003` and `E004`.)

Use cases:
- the development defaults (console backend, debug on) raise nothing
- E001, in `check --deploy`: the console backend with DJANGO_DEBUG off
- E002: the outbox backend without MAIL_ALLOW_OUTBOX
- E003: MAIL_ALLOW_OUTBOX on while DJANGO_DEBUG is off
- E004: a backend name that is not registered, or a real backend with its settings missing (Brevo with no key or no
  sender)
- a real backend with its settings, debug off, raises nothing
- the two hooks Django runs are thin: the deploy one gives E001, the other gives E002 to E004
"""

from accounts.mail.checks import MailSafety, mail_backend_is_fit_for_production, mail_backend_is_usable
from accounts.mail.mailer import Mailer, SendResult


class Real(Mailer):
    """A real provider's adapter: it needs `REAL_KEY` when `lacks` is on."""

    key = "real"
    lacks = False

    def send(self, message):
        return SendResult("x")

    @classmethod
    def from_settings(cls):
        return cls()

    def missing_config(self):
        return ["REAL_KEY"] if Real.lacks else []


class Dev(Real):
    key = "dev"


def ids(errors):
    return [e.id for e in errors]


def safety(backend, debug, allow_outbox=False):
    classes = {"console": Dev, "outbox": Dev, "real": Real}
    return MailSafety(backend=backend, debug=debug, allow_outbox=allow_outbox, classes=classes)


def test_the_development_defaults_raise_nothing():
    assert safety("console", debug=True).errors() == [] and safety("console", debug=True).deploy_errors() == []


def test_the_console_backend_in_production_is_e001_only_for_the_deploy_check():
    assert ids(safety("console", debug=False).deploy_errors()) == ["accounts.E001"]
    assert safety("console", debug=False).errors() == []


def test_the_outbox_without_its_switch_is_e002():
    assert ids(safety("outbox", debug=True, allow_outbox=False).errors()) == ["accounts.E002"]
    assert safety("outbox", debug=True, allow_outbox=True).errors() == []


def test_the_switch_with_debug_off_is_e003():
    assert "accounts.E003" in ids(safety("outbox", debug=False, allow_outbox=True).errors())
    assert "accounts.E003" in ids(safety("real", debug=False, allow_outbox=True).errors())


def test_an_unknown_backend_or_missing_settings_is_e004():
    assert ids(safety("carrier-pigeon", debug=False).errors()) == ["accounts.E004"]
    Real.lacks = True
    try:
        assert ids(safety("real", debug=False).errors()) == ["accounts.E004"]
    finally:
        Real.lacks = False


def test_a_real_backend_with_its_settings_raises_nothing():
    assert safety("real", debug=False).errors() == [] and safety("real", debug=False).deploy_errors() == []


def test_the_hooks_django_runs_are_thin(settings):
    settings.DEBUG, settings.MAIL_BACKEND, settings.MAIL_ALLOW_OUTBOX = False, "console", False

    assert ids(mail_backend_is_fit_for_production()) == ["accounts.E001"]
    assert mail_backend_is_usable() == []
