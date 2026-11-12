"""Making a code (plan 5.6): a new code for the same purpose and email cancels the old one; only its hash is kept."""

import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime

from django.db import transaction

from ..clock import Clock, SystemClock
from ..dblock import DbLock
from ..models import PendingSignup, User, VerificationCode
from .config import VerificationSettings
from .hasher import CodeHasher


@dataclass(frozen=True)
class IssuedCode:
    """The code, once, on its way to the mail. It is not stored anywhere."""

    code: str
    row_id: uuid.UUID
    expires_at: datetime
    minutes: int


class CodeIssuer:
    def __init__(
        self,
        hasher: CodeHasher | None = None,
        clock: Clock | None = None,
        settings: VerificationSettings | None = None,
    ):
        self.hasher = hasher or CodeHasher()
        self.clock = clock or SystemClock()
        self._settings = settings

    @property
    def settings(self) -> VerificationSettings:
        return self._settings or VerificationSettings.from_settings()

    def issue(
        self,
        purpose: str,
        email_canonical: str,
        *,
        pending: PendingSignup | None = None,
        user: User | None = None,
        ip: str | None = None,
    ) -> IssuedCode:
        config, now = self.settings, self.clock.now()
        with transaction.atomic():
            DbLock.acquire(f"code:{purpose}:{email_canonical}")  # two sends for one email take turns
            VerificationCode.objects.filter(
                purpose=purpose, email_canonical=email_canonical, consumed_at__isnull=True, invalidated_at__isnull=True
            ).update(invalidated_at=now)
            row_id = uuid.uuid4()
            code = f"{secrets.randbelow(10**config.code_digits):0{config.code_digits}d}"
            row = VerificationCode.objects.create(
                id=row_id,
                purpose=purpose,
                email_canonical=email_canonical,
                pending=pending,
                user=user,
                code_hash=self.hasher.hash(code, purpose, email_canonical, row_id),
                max_attempts=config.max_attempts,
                created_at=now,
                expires_at=now + config.code_ttl,
                requested_ip=ip or None,
            )
        return IssuedCode(code=code, row_id=row_id, expires_at=row.expires_at, minutes=config.code_minutes)
