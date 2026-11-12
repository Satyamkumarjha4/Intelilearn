"""The five emails sign-in sends (phase 11). Plain, warm, one big code, no links.

A code is in the body and not in the subject (a lock-screen preview must not show it); no email carries a link (a mail
scanner that opens one would spend a token, and there is none to spend); and a learner reads "code", never OTP.
Each message
has a text part and an HTML part that say the same thing. Mail goes to the address as typed.
"""

import html

from django.conf import settings

from .mailer import MailMessage


class MailTemplates:
    SIGN_OFF = "Socra"

    def signup_code(self, to: str, code: str, minutes: int) -> MailMessage:
        return self._code_mail(
            "signup_code", to, code, minutes, "Your Socra code", "Enter it to finish creating your account."
        )

    def login_code(self, to: str, code: str, minutes: int) -> MailMessage:
        return self._code_mail("login_code", to, code, minutes, "Your Socra code", "Enter it to finish signing in.")

    def reset_code(self, to: str, code: str, minutes: int) -> MailMessage:
        return self._code_mail(
            "reset_code", to, code, minutes, "Choose a new Socra password", "Enter it to choose a new password."
        )

    def owner_notice(self, to: str) -> MailMessage:
        """To the owner of an address that someone tried to create an account with, when it already has one."""
        lines = [
            "Someone tried to create a Socra account with this email address, which already has one.",
            "If it was you, sign in instead. "
            'If you don\'t remember your password, choose "Forgot password" on the sign-in page.',
            "If it wasn't you, you can ignore this email. Nothing has changed.",
        ]
        return self._mail("owner_notice", to, "Someone used your email address on Socra", lines)

    def use_google_notice(self, to: str) -> MailMessage:
        """To the owner of an address that signs in with Google, when they ask to choose a password."""
        lines = [
            "This email address signs in to Socra with Google, so it has no password to reset.",
            'Go to the sign-in page and choose "Continue with Google".',
            "If you didn't ask for this, you can ignore this email.",
        ]
        return self._mail("use_google_notice", to, "Sign in to Socra with Google", lines)

    def takeover_notice(self, to: str, contact: str | None = None) -> MailMessage:
        """To the address of an account that someone has just taken over by signing in with Google (an account whose
        email nobody had proved). The owner of the inbox did it, or someone with access to it: either way they are
        told what changed and who to tell."""
        contact = contact or settings.CONTACT_EMAIL
        lines = [
            "Your Socra account now signs in with Google. The old password no longer works.",
            'To choose a password of your own, use "Forgot password" on the sign-in page.',
            f"If this wasn't you, please tell us at {contact}.",
        ]
        return self._mail("takeover_notice", to, "Your Socra account now signs in with Google", lines)

    def _code_mail(self, kind: str, to: str, code: str, minutes: int, subject: str, purpose: str) -> MailMessage:
        lines = [
            f"Your Socra code is {code}",
            f"It works for {minutes} minutes. {purpose}",
            "If you didn't ask for this, you can ignore this email. Nobody can use your address without the code.",
        ]
        return self._mail(kind, to, subject, lines, big=code)

    def _mail(self, kind: str, to: str, subject: str, lines: list[str], big: str = "") -> MailMessage:
        text = "Hi,\n\n" + "\n\n".join(lines) + f"\n\n{self.SIGN_OFF}\n"
        paragraphs = []
        for line in lines:
            safe = html.escape(line)
            if big and line.endswith(big):  # the line that holds the code: the code is set large
                style = "font-size:28px;letter-spacing:6px;font-weight:bold"
                safe = f'{html.escape(line[: -len(big)])}<br><span style="{style}">{html.escape(big)}</span>'
            paragraphs.append(f"<p>{safe}</p>")
        body = "<p>Hi,</p>" + "".join(paragraphs) + f"<p>{self.SIGN_OFF}</p>"
        return MailMessage(to=to, kind=kind, subject=subject, text=text, html=body)
