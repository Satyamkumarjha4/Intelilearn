"""The learners list: who is using Socra and how much. Read-only; accounts are changed in the Django admin.

It also says which sign-ins need a look (an email never proved, an account from before verification, a locked email),
so support can find them without opening every learner."""

from datetime import datetime, timedelta

from django.db.models import Count, Exists, Max, OuterRef, Q, QuerySet
from django.db.models.functions import Greatest
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from accounts.models import EmailLock, Profile, User


class VerificationFilters:
    """The sign-in states a support person looks for, each a condition on the learners list. They count **open**
    accounts only (not closed, not erased): a closed or erased account has nobody to help. A state is one entry here, so
    a new one is added without touching the query or the summary. `locked` reads the `email_locked` annotation that
    `LearnerQuery` adds."""

    OPEN = Q(is_active=True, deleted_at__isnull=True)
    CONDITIONS: dict[str, Q] = {
        "unverified": OPEN & Q(email_verified_at__isnull=True),
        "legacy": OPEN & Q(email_verified_at__isnull=False, email_verification_source=User.VerificationSource.LEGACY),
        "locked": OPEN & Q(email_locked=True),
    }

    @classmethod
    def names(cls) -> list[str]:
        return list(cls.CONDITIONS)

    @classmethod
    def apply(cls, members: QuerySet[User], name: str) -> QuerySet[User]:
        """The learners in this state; an empty name is everyone, an unknown one is a `400` naming `verification`."""
        if not name:
            return members
        if name not in cls.CONDITIONS:
            raise ValidationError({"verification": [f"Choose one of: {', '.join(cls.names())}."]})
        return members.filter(cls.CONDITIONS[name])

    @classmethod
    def counts(cls, members: QuerySet[User]) -> dict[str, int]:
        """How many learners are in each state, in one query."""
        return members.aggregate(**{name: Count("pk", filter=cond) for name, cond in cls.CONDITIONS.items()})


class LearnerQuery:
    def __init__(self, now: datetime | None = None):
        self._now = now

    @property
    def now(self) -> datetime:
        return self._now or timezone.now()

    def with_lock_state(self, members: QuerySet[User]) -> QuerySet[User]:
        """Each learner with `email_locked`: whether their canonical email is locked right now (one subquery)."""
        live = EmailLock.objects.filter(email_canonical=OuterRef("email_canonical"), locked_until__gt=self.now)
        return members.annotate(email_locked=Exists(live))

    def queryset(self, search: str = "", verification: str = "") -> QuerySet[User]:
        """Members with their profile, their lesson count and when they were last active (the later of their latest
        lesson activity and their last sign-in), in one query. `verification` keeps one sign-in state."""
        members = self.with_lock_state(User.objects.select_related("profile")).annotate(
            lessons_count=Count("lessons", distinct=True),
            last_activity=Greatest(Max("lessons__updated_at"), "last_login"),
        )
        members = VerificationFilters.apply(members, verification)
        if search := search.strip():
            members = members.filter(Q(name__icontains=search) | Q(email__icontains=search))
        return members


class LearnerSummary:
    ACTIVE_DAYS = 7

    def of_everyone(self, now: datetime | None = None) -> dict:
        since = (now or timezone.now()) - timedelta(days=self.ACTIVE_DAYS)
        incomplete = Q(education_level="") | Q(learning_preference="") | Q(goal="")
        return {
            "total": User.objects.count(),
            "active_7d": User.objects.filter(Q(last_login__gte=since) | Q(lessons__updated_at__gte=since))
            .distinct()
            .count(),
            "profile_complete": Profile.objects.exclude(incomplete).count(),
            "staff": User.objects.filter(is_staff=True).count(),
            **VerificationFilters.counts(LearnerQuery(now).with_lock_state(User.objects.all())),
        }
