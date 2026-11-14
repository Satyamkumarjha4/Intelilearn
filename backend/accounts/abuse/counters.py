"""What the abuse board shows (plan D14): numbers read from what the app already keeps, nothing new to maintain.

Accounts made come from `SignupRecord`, codes sent from the mail log (`OutboundMail`, the three code kinds), failed
checks, refused throwaway addresses and failed challenges from `AuthEvent`. The top lists name addresses and email
**domains**, never an email. Every window is counted in UTC days; a day with no events is a row of zeros, so a chart
has no holes."""

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from django.db.models import Count
from django.db.models.functions import TruncDate

from ..clock import Clock, SystemClock
from ..models import AuthEvent, EmailLock, OutboundMail, SignupRecord

CODE_KINDS = ("signup_code", "login_code", "reset_code")


@dataclass(frozen=True)
class DayRow:
    day: date
    accounts_made: int = 0
    codes_sent: int = 0
    failed_checks: int = 0
    disposable_refused: int = 0
    captcha_failed: int = 0

    def as_dict(self) -> dict:
        return {**self.__dict__, "day": self.day.isoformat()}


@dataclass(frozen=True)
class TopEntry:
    name: str
    count: int

    def as_dict(self) -> dict:
        return {"name": self.name, "count": self.count}


class AbuseCounters:
    def __init__(self, clock: Clock | None = None):
        self.clock = clock or SystemClock()

    def daily(self, days: int = 14) -> list[DayRow]:
        """One row per UTC day for the last `days` days, oldest first, today last."""
        today = self.clock.now().date()
        first = today - timedelta(days=days - 1)
        start = datetime.combine(first, datetime.min.time(), tzinfo=self.clock.now().tzinfo)
        counts: dict[str, Counter] = {key: Counter() for key in ("made", "codes", *AuthEvent.Kind.values)}
        for row in (
            SignupRecord.objects.filter(created_at__gte=start)
            .annotate(day=TruncDate("created_at"))
            .values("day")
            .annotate(n=Count("id"))
        ):
            counts["made"][row["day"]] = row["n"]
        for row in (
            OutboundMail.objects.filter(created_at__gte=start, kind__in=CODE_KINDS)
            .annotate(day=TruncDate("created_at"))
            .values("day")
            .annotate(n=Count("id"))
        ):
            counts["codes"][row["day"]] = row["n"]
        for row in (
            AuthEvent.objects.filter(created_at__gte=start)
            .annotate(day=TruncDate("created_at"))
            .values("day", "kind")
            .annotate(n=Count("id"))
        ):
            counts[row["kind"]][row["day"]] = row["n"]
        rows = []
        for offset in range(days):
            day = first + timedelta(days=offset)
            rows.append(
                DayRow(
                    day=day,
                    accounts_made=counts["made"][day],
                    codes_sent=counts["codes"][day],
                    failed_checks=counts[AuthEvent.Kind.CHECK_FAILED][day],
                    disposable_refused=counts[AuthEvent.Kind.DISPOSABLE_REFUSED][day],
                    captcha_failed=counts[AuthEvent.Kind.CAPTCHA_FAILED][day],
                )
            )
        return rows

    def top_addresses(self, hours: int = 24, limit: int = 5) -> list[TopEntry]:
        """The client addresses behind the most accounts made, failed checks and refused throwaway addresses lately."""
        since = self.clock.now() - timedelta(hours=hours)
        found: Counter = Counter()
        for model in (SignupRecord, AuthEvent):
            for row in (
                model.objects.filter(created_at__gte=since, ip__isnull=False).values("ip").annotate(n=Count("id"))
            ):
                found[row["ip"]] += row["n"]
        return [TopEntry(ip, n) for ip, n in found.most_common(limit)]

    def top_domains(self, hours: int = 24, limit: int = 5) -> list[TopEntry]:
        """The email domains behind the most accounts made and refused sign-ups lately."""
        since = self.clock.now() - timedelta(hours=hours)
        found: Counter = Counter()
        for model in (SignupRecord, AuthEvent):
            for row in (
                model.objects.filter(created_at__gte=since)
                .exclude(email_domain="")
                .values("email_domain")
                .annotate(n=Count("id"))
            ):
                found[row["email_domain"]] += row["n"]
        return [TopEntry(domain, n) for domain, n in found.most_common(limit)]

    def locked_emails(self) -> int:
        """Addresses whose codes are paused right now."""
        return EmailLock.objects.filter(locked_until__gt=self.clock.now()).count()
