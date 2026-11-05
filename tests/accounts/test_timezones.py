"""Unit under test: `accounts.timezones`: `TimeZoneNames` (which names are real, and the default) and `ProfileTimezone`
(the rule for changing a learner's zone).

Why: the day a learner's streak and daily credit belong to is their local day, so the zone has to be a real IANA name,
and it must not be possible to hop between zones to be "active" twice in one real day. The rule is what stops that:
the first value is free (it comes from the browser at sign-up), every later change locks the next one for 30 days.

Use cases:
- a name is valid when it is in the system's zone database (links such as Asia/Calcutta and UTC too); blank, other
  types, a made-up name and a path-like name are not
- a learner who never set a zone is on Asia/Kolkata; one who did is on their own
- the first value set does not start the lock; setting the same value again changes nothing and never locks
- a later change is saved, stamps `timezone_changed_at` and locks the next change for 30 days
- a change inside the 30 days is refused with `timezone_locked` and the instant it opens; on the 30th day it works
- `locked_until` is empty for a zone never changed and for a lock that has passed
- a refused change leaves the profile as it was
"""

from datetime import UTC, datetime, timedelta

import pytest

from accounts.models import Profile
from accounts.timezones import ProfileTimezone, TimezoneLocked, TimeZoneNames

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


class TestTimeZoneNames:
    @pytest.mark.parametrize("name", ["Asia/Kolkata", "Asia/Calcutta", "America/New_York", "Europe/London", "UTC"])
    def test_a_name_in_the_zone_database_is_valid(self, name):
        assert TimeZoneNames.is_valid(name) is True

    @pytest.mark.parametrize("name", ["", "   ", "Mars/Olympus", "asia/kolkata ", "../etc/passwd", "IST", None, 5, []])
    def test_anything_else_is_not(self, name):
        assert TimeZoneNames.is_valid(name) is False

    def test_a_learner_with_no_zone_is_on_kolkata_time_and_one_with_a_zone_on_their_own(self):
        assert TimeZoneNames.DEFAULT == "Asia/Kolkata"
        assert TimeZoneNames.effective("") == "Asia/Kolkata"
        assert TimeZoneNames.effective("Europe/London") == "Europe/London"


@pytest.fixture
def profile(user):
    return user.profile


def rule(now=NOW) -> ProfileTimezone:
    return ProfileTimezone(now=lambda: now)


@pytest.mark.django_db
class TestProfileTimezone:
    def test_the_first_value_is_set_without_starting_the_lock(self, profile):
        rule().apply(profile, "Asia/Kolkata")

        assert profile.timezone == "Asia/Kolkata" and profile.timezone_changed_at is None
        assert rule().locked_until(profile) is None

    def test_a_second_value_right_after_the_first_is_allowed_and_starts_the_lock(self, profile):
        rule().apply(profile, "Asia/Kolkata")

        rule().apply(profile, "Europe/London")

        assert profile.timezone == "Europe/London" and profile.timezone_changed_at == NOW
        assert rule().locked_until(profile) == NOW + timedelta(days=30)

    def test_setting_the_same_value_again_changes_nothing_and_does_not_lock(self, profile):
        rule().apply(profile, "Asia/Kolkata")

        rule().apply(profile, "Asia/Kolkata")

        assert profile.timezone_changed_at is None

    def test_the_same_value_is_fine_even_while_locked(self, profile):
        rule().apply(profile, "Asia/Kolkata")
        rule().apply(profile, "Europe/London")

        rule().apply(profile, "Europe/London")

        assert profile.timezone == "Europe/London"

    def test_a_change_inside_the_30_days_is_refused_with_the_instant_it_opens(self, profile):
        rule().apply(profile, "Asia/Kolkata")
        rule().apply(profile, "Europe/London")

        with pytest.raises(TimezoneLocked) as refused:
            rule(NOW + timedelta(days=29, hours=23)).apply(profile, "America/New_York")

        assert refused.value.status_code == 409 and refused.value.get_codes() == "timezone_locked"
        assert refused.value.extra == {"locked_until": (NOW + timedelta(days=30)).isoformat()}
        assert profile.timezone == "Europe/London" and profile.timezone_changed_at == NOW

    def test_a_change_after_the_30_days_works_and_locks_again(self, profile):
        rule().apply(profile, "Asia/Kolkata")
        rule().apply(profile, "Europe/London")
        later = NOW + timedelta(days=30)

        rule(later).apply(profile, "America/New_York")

        assert profile.timezone == "America/New_York" and profile.timezone_changed_at == later
        assert rule(later).locked_until(profile) == later + timedelta(days=30)

    def test_a_lock_that_has_passed_is_no_lock(self, profile):
        rule().apply(profile, "Asia/Kolkata")
        rule().apply(profile, "Europe/London")

        assert rule(NOW + timedelta(days=30)).locked_until(profile) is None
        assert rule(NOW + timedelta(days=31)).locked_until(profile) is None

    def test_apply_only_sets_attributes_and_leaves_saving_to_the_caller(self, profile):
        rule().apply(profile, "Europe/London")

        assert Profile.objects.get(pk=profile.pk).timezone == ""
