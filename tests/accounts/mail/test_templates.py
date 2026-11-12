"""Unit under test: `accounts.mail.templates.MailTemplates`, the six emails sign-in sends.

Why: a code in an email is a credential for ten minutes. It must be easy to read, must not show on a lock screen or in a
mail list (so not in the subject), must not hide behind a link that a mail scanner would open and spend, and the
words must
follow the product's rules (a learner reads "code", never OTP). The plain-text and HTML parts are what a person's
mail app
shows, so they must say the same thing.

Use cases:
- each code email (sign-up, sign-in, password reset) carries the code once in the text and once in the HTML, and
  never in
  the subject, and says how long it lasts
- the notice to the owner of an address that someone tried to sign up with, the notice that an address signs in with
  Google, and the notice that an account was taken over by a Google sign-in carry no code and say what to do
- the takeover notice says the account now signs in with Google, that the old password no longer works, and who to
  contact if it was not them (from the settings unless given)
- no email carries a link (so nothing is opened by a scanner) and none uses an internal word
- the HTML part escapes what it is given and says the same as the text
- every message is addressed to the address as typed, and has a kind the mail log can show
"""

import re

import pytest

from accounts.mail.templates import MailTemplates

CODE = "493027"
TO = "Ada.Lovelace@Example.com"
INTERNAL_WORDS = re.compile(r"\b(otp|token|pending|canonical|identity provider|verification code)\b", re.I)


def code_mails():
    t = MailTemplates()
    return [t.signup_code(TO, CODE, 10), t.login_code(TO, CODE, 10), t.reset_code(TO, CODE, 10)]


def notices():
    t = MailTemplates()
    return [t.owner_notice(TO), t.use_google_notice(TO), t.takeover_notice(TO, "help@example.org")]


@pytest.mark.parametrize("mail", code_mails(), ids=lambda m: m.kind)
def test_a_code_email_carries_the_code_once_in_each_part_and_not_in_the_subject(mail):
    assert mail.text.count(CODE) == 1
    assert mail.html.count(CODE) == 1
    assert CODE not in mail.subject and not re.search(r"\d{4,}", mail.subject)
    assert "10 minutes" in mail.text and "10 minutes" in mail.html


@pytest.mark.parametrize("mail", notices(), ids=lambda m: m.kind)
def test_a_notice_carries_no_code(mail):
    assert not re.search(r"\d{4,}", mail.text + mail.html + mail.subject)


def test_the_takeover_notice_says_what_changed_and_who_to_contact():
    takeover = notices()[2]

    assert takeover.kind == "takeover_notice" and takeover.to == TO
    text = takeover.text
    assert "now signs in with Google" in text and "old password no longer works" in text
    assert "help@example.org" in text and "help@example.org" in takeover.html
    assert "wasn't you" in text


def test_the_takeover_notice_reads_the_contact_address_from_the_settings_when_none_is_given(settings):
    settings.CONTACT_EMAIL = "someone@contact.example"

    assert "someone@contact.example" in MailTemplates().takeover_notice(TO).text


def test_the_notices_say_what_to_do():
    owner, google, _ = notices()

    assert "someone" in owner.text.lower() and "nothing has changed" in owner.text.lower()
    assert "sign in" in owner.text.lower()
    assert "Google" in google.text and "Continue with Google" in google.text


@pytest.mark.parametrize("mail", [*code_mails(), *notices()], ids=lambda m: m.kind)
def test_no_email_has_a_link_or_an_internal_word(mail):
    for part in (mail.subject, mail.text, mail.html):
        assert "http" not in part.lower() and "<a " not in part.lower()
        assert not INTERNAL_WORDS.search(part), part


@pytest.mark.parametrize("mail", [*code_mails(), *notices()], ids=lambda m: m.kind)
def test_each_message_is_addressed_as_typed_and_has_a_kind(mail):
    assert mail.to == TO
    assert mail.kind and mail.subject


def test_the_kinds_are_the_six_the_mail_log_shows():
    assert {m.kind for m in [*code_mails(), *notices()]} == {
        "signup_code",
        "login_code",
        "reset_code",
        "owner_notice",
        "use_google_notice",
        "takeover_notice",
    }


def test_the_html_part_escapes_what_it_is_given_and_says_what_the_text_says():
    mail = MailTemplates().signup_code("x@example.com", "<b>1</b>", 10)

    assert "<b>1</b>" not in mail.html and "&lt;b&gt;1&lt;/b&gt;" in mail.html
    plain_from_html = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", mail.html)).strip()
    for sentence in ("10 minutes", "ignore this email"):
        assert sentence in plain_from_html and sentence in mail.text
