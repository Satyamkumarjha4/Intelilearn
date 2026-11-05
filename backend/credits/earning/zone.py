"""Which time zone a learner's day is counted in: their own, or Asia/Kolkata when they never set one."""

from accounts.models import Profile
from accounts.timezones import TimeZoneNames


class LearnerZone:
    @staticmethod
    def of(user) -> str:
        stored = Profile.objects.filter(user_id=user.pk).values_list("timezone", flat=True).first()
        return TimeZoneNames.effective(stored or "")
