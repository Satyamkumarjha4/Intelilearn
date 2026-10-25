"""The learners list: who is using Socra and how much. Read-only; accounts are changed in the Django admin."""

from datetime import datetime, timedelta

from django.db.models import Count, Max, Q, QuerySet
from django.db.models.functions import Greatest
from django.utils import timezone

from accounts.models import Profile, User


class LearnerQuery:
    def queryset(self, search: str = "") -> QuerySet[User]:
        """Members with their profile, their lesson count and when they were last active (the later of their latest
        lesson activity and their last sign-in), in one query."""
        members = User.objects.select_related("profile").annotate(
            lessons_count=Count("lessons", distinct=True),
            last_activity=Greatest(Max("lessons__updated_at"), "last_login"),
        )
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
        }
