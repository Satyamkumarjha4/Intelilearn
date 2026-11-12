"""Unit under test: `accounts.mail.registry.MailBackends`, which finds the mailer `MAIL_BACKEND` names, and the
development
backends it holds (`ConsoleMailer`, `OutboxMailer`).

Why: sign-in cannot work without email, and which provider sends it must be a setting, not a code change (Brevo today, a
scale-up provider tomorrow). The two development backends exist so a developer and the browser tests can read a
code without a
provider; each is dangerous in production (a printed code, a readable outbox), so each refuses to send there, on
top of the
start-up checks.

Use cases:
- the backend named by the setting is the one used; an unknown name is an error that lists the known ones
- the real and the development backends are all registered under their keys
- the console backend writes the message (and so the code) to the log only with DJANGO_DEBUG on, and refuses otherwise
- the outbox backend keeps the body for the browser tests, only with its own switch on, and refuses otherwise
- a test can hand the registry its own classes and choice, so nothing global changes
"""

import logging

import pytest

from accounts.mail.mailer import Mailer, MailMessage, PermanentMailError, SendResult
from accounts.mail.registry import MailBackends, UnknownMailBackend

MESSAGE = MailMessage(to="ada@example.com", kind="signup_code", subject="Your Socra code", text="Code 123456")


class Recorder(Mailer):
    key = "recorder"

    def __init__(self):
        self.sent = []

    def send(self, message):
        self.sent.append(message)
        return SendResult("r1")

    @classmethod
    def from_settings(cls):
        return cls()


def test_the_backend_the_setting_names_is_the_one_used(settings):
    settings.MAIL_BACKEND = "recorder"

    assert isinstance(MailBackends(classes={"recorder": Recorder}).current(), Recorder)


def test_an_unknown_backend_is_an_error_that_lists_the_known_ones(settings):
    settings.MAIL_BACKEND = "carrier-pigeon"

    with pytest.raises(UnknownMailBackend) as raised:
        MailBackends(classes={"recorder": Recorder}).current()

    assert "carrier-pigeon" in str(raised.value) and "recorder" in str(raised.value)


def test_the_real_and_development_backends_are_registered():
    assert {"brevo", "console", "outbox"} <= set(MailBackends.REGISTERED)


def test_the_console_backend_writes_the_message_to_the_log_with_debug_on(settings, caplog):
    settings.DEBUG = True
    settings.MAIL_BACKEND = "console"

    with caplog.at_level(logging.INFO, logger="accounts.mail.console"):
        MailBackends().current().send(MESSAGE)

    assert "Code 123456" in caplog.text and "ada@example.com" in caplog.text


def test_the_console_backend_refuses_to_send_without_debug(settings, caplog):
    settings.DEBUG = False
    settings.MAIL_BACKEND = "console"

    with pytest.raises(PermanentMailError), caplog.at_level(logging.INFO):
        MailBackends().current().send(MESSAGE)

    assert "123456" not in caplog.text


def test_the_outbox_backend_keeps_the_body_with_its_switch_on_and_refuses_without(settings):
    settings.DEBUG, settings.MAIL_ALLOW_OUTBOX, settings.MAIL_BACKEND = True, True, "outbox"
    outbox = MailBackends().current()

    assert outbox.keeps_body is True
    assert outbox.send(MESSAGE).message_id == "outbox"

    settings.MAIL_ALLOW_OUTBOX = False
    with pytest.raises(PermanentMailError):
        outbox.send(MESSAGE)
    settings.MAIL_ALLOW_OUTBOX, settings.DEBUG = True, False
    with pytest.raises(PermanentMailError):
        outbox.send(MESSAGE)


def test_only_the_outbox_keeps_a_body():
    assert [k for k, cls in MailBackends.REGISTERED.items() if cls.keeps_body] == ["outbox"]
