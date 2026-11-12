"""The signup ticket (plan T19): a signed value that holds the id of the browser's own pending sign-up.

`POST /auth/register` hands it out as the `lc_signup` cookie. The code only works with a ticket whose id is the **live**
pending row's id, so whoever registers a victim's address again (a new row, a new id) cannot make the victim's own code
finish the sign-up with the attacker's password: the victim's browser holds the old id. The ticket is not stored; it
carries no authority except "I am the browser that registered this row"."""

import uuid

from django.core import signing

from .config import VerificationSettings


class SignupTicket:
    COOKIE = "lc_signup"
    SALT = "accounts.signup-ticket"

    def __init__(self, settings: VerificationSettings | None = None):
        self._settings = settings

    @property
    def settings(self) -> VerificationSettings:
        return self._settings or VerificationSettings.from_settings()

    def issue(self, pending_id: uuid.UUID) -> str:
        return signing.dumps(str(pending_id), salt=self.SALT, compress=False)

    def decoy(self) -> str:
        """A ticket for a row that does not exist: what a known address is given, so the reply looks the same."""
        return self.issue(uuid.uuid4())

    def read(self, token: str | None) -> uuid.UUID | None:
        """The pending id in a ticket, or None for a missing, forged, tampered or expired one."""
        if not token:
            return None
        try:
            return uuid.UUID(signing.loads(token, salt=self.SALT, max_age=self.settings.ticket_ttl.total_seconds()))
        except (signing.BadSignature, ValueError, TypeError):
            return None
