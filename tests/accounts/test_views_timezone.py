"""Unit under test: the time zone on `POST /api/auth/register` and `GET/PUT/PATCH /api/profile`, and the
`account_ready` signal that registration sends.

Why: the learner's day (for the daily credit and the streak) is the day in their zone. The zone is taken from the
browser at sign-up, so a sign-up must never fail because of it, and can be changed later but only once per 30 days.
`account_ready` is the one event the signup credits will hang from, so it has to be sent exactly when an account is
made and never when registration is refused.

Use cases:
- registering with the browser's zone stores it without starting the lock; registering without one, or with a name no
  zone database knows, still creates the account and leaves the zone unset
- a new profile reports no zone, the one in effect (Asia/Kolkata) and no lock
- PATCH sets a zone; an unknown or blank zone is refused with a message on the field
- a first value set on the profile is free; the next change works and locks, and the profile says until when
- a change inside the lock is refused with 409 `timezone_locked` and the instant it opens, and nothing else in the
  same request is saved
- setting the same zone again is not a change; PUT (the profile page) can carry the zone too
- entering the right code sends `account_ready` once with the new user, the zone already stored; a sign-up that is
  waiting for its code, refused, or answered with a wrong code sends nothing; a receiver that raises does not undo the
  account
"""

from datetime import UTC, datetime, timedelta

import pytest
from django.utils import timezone

from accounts.models import Profile, User
from accounts.signals import account_ready

pytestmark = pytest.mark.django_db


@pytest.fixture
def register(signup):
    """Sign up as a new person and enter the mailed code: the response of the code check (the account, signed in)."""

    def _register(**extra):
        return signup.complete(**{"email": "new@example.com", **extra})

    return _register


class TestRegistrationZone:
    def test_the_browsers_zone_is_stored_without_starting_the_lock(self, register):
        assert register(timezone="Europe/London").status_code == 200

        profile = Profile.objects.get(user__email="new@example.com")
        assert profile.timezone == "Europe/London" and profile.timezone_changed_at is None

    def test_no_zone_leaves_it_unset(self, register):
        assert register().status_code == 200

        assert Profile.objects.get(user__email="new@example.com").timezone == ""

    @pytest.mark.parametrize("name", ["Mars/Olympus", "", "IST", "../x"])
    def test_a_zone_nobody_knows_does_not_stop_the_account_being_made(self, register, name):
        assert register(timezone=name).status_code == 200

        assert Profile.objects.get(user__email="new@example.com").timezone == ""


class TestProfileZone:
    def test_a_new_profile_reports_no_zone_the_default_in_effect_and_no_lock(self, signed_in_client):
        body = signed_in_client.get("/api/profile").json()

        assert body["timezone"] == "" and body["effective_timezone"] == "Asia/Kolkata"
        assert body["timezone_locked_until"] is None

    def test_a_zone_is_set_with_patch(self, signed_in_client, user):
        response = signed_in_client.patch("/api/profile", {"timezone": "Europe/London"}, format="json")

        assert response.status_code == 200
        assert (
            response.json()["timezone"] == "Europe/London" and response.json()["effective_timezone"] == "Europe/London"
        )
        user.profile.refresh_from_db()
        assert user.profile.timezone == "Europe/London"

    @pytest.mark.parametrize("name", ["Mars/Olympus", "", "  "])
    def test_an_unknown_or_blank_zone_is_refused_on_the_field(self, signed_in_client, user, name):
        response = signed_in_client.patch("/api/profile", {"timezone": name}, format="json")

        assert response.status_code == 400 and "timezone" in response.json()["fields"]
        user.profile.refresh_from_db()
        assert user.profile.timezone == ""

    def test_the_first_value_is_free_the_next_change_works_and_locks_for_30_days(self, signed_in_client, user):
        signed_in_client.patch("/api/profile", {"timezone": "Asia/Kolkata"}, format="json")
        assert signed_in_client.get("/api/profile").json()["timezone_locked_until"] is None

        changed = signed_in_client.patch("/api/profile", {"timezone": "Europe/London"}, format="json")

        assert changed.status_code == 200
        user.profile.refresh_from_db()
        stamp = user.profile.timezone_changed_at
        assert stamp is not None and abs(timezone.now() - stamp) < timedelta(minutes=1)
        expected = (stamp + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M")
        assert changed.json()["timezone_locked_until"].startswith(expected)

    def test_a_change_inside_the_lock_is_a_409_with_the_instant_it_opens_and_saves_nothing_else(
        self, signed_in_client, user
    ):
        signed_in_client.patch("/api/profile", {"timezone": "Asia/Kolkata"}, format="json")
        signed_in_client.patch("/api/profile", {"timezone": "Europe/London"}, format="json")
        user.profile.refresh_from_db()
        opens = (user.profile.timezone_changed_at + timedelta(days=30)).isoformat()

        response = signed_in_client.patch(
            "/api/profile", {"timezone": "America/New_York", "name": "Renamed", "notes": "x"}, format="json"
        )

        assert response.status_code == 409
        assert response.json()["code"] == "timezone_locked" and response.json()["locked_until"] == opens
        user.profile.refresh_from_db()
        user.refresh_from_db()
        assert user.profile.timezone == "Europe/London" and user.name == "Ada Lovelace" and user.profile.notes == ""

    def test_a_lock_that_has_run_out_lets_the_zone_change_again(self, signed_in_client, user):
        Profile.objects.filter(user=user).update(
            timezone="Europe/London", timezone_changed_at=timezone.now() - timedelta(days=31)
        )

        response = signed_in_client.patch("/api/profile", {"timezone": "America/New_York"}, format="json")

        assert response.status_code == 200 and response.json()["timezone"] == "America/New_York"

    def test_the_same_zone_is_not_a_change_even_inside_the_lock(self, signed_in_client, user):
        Profile.objects.filter(user=user).update(timezone="Europe/London", timezone_changed_at=timezone.now())

        response = signed_in_client.patch("/api/profile", {"timezone": "Europe/London", "notes": "hi"}, format="json")

        assert response.status_code == 200 and response.json()["notes"] == "hi"

    def test_the_profile_page_can_send_the_zone_with_the_whole_profile(self, signed_in_client):
        whole = {
            "education_level": "undergraduate",
            "grade_or_year": "2nd year",
            "field_of_study": "CS",
            "preferred_language": "en",
            "learning_preference": "hands_on",
            "goal": "exam_prep",
            "timezone": "Asia/Kolkata",
        }

        response = signed_in_client.put("/api/profile", whole, format="json")

        assert response.status_code == 200 and response.json()["timezone"] == "Asia/Kolkata"

    def test_a_put_without_a_zone_leaves_it_alone(self, signed_in_client, user):
        Profile.objects.filter(user=user).update(timezone="Europe/London")
        whole = {
            "education_level": "undergraduate", "grade_or_year": "2nd year", "field_of_study": "CS",
            "preferred_language": "en", "learning_preference": "hands_on", "goal": "exam_prep",
        }  # fmt: skip

        assert signed_in_client.put("/api/profile", whole, format="json").status_code == 200

        user.profile.refresh_from_db()
        assert user.profile.timezone == "Europe/London"

    def test_a_lock_in_the_past_is_not_reported(self, signed_in_client, user):
        long_ago = datetime(2026, 1, 1, tzinfo=UTC)
        Profile.objects.filter(user=user).update(timezone="Europe/London", timezone_changed_at=long_ago)

        assert signed_in_client.get("/api/profile").json()["timezone_locked_until"] is None


class TestAccountReady:
    @pytest.fixture
    def received(self):
        calls = []

        def receiver(sender, **kwargs):
            calls.append((sender, kwargs["user"]))

        account_ready.connect(receiver, weak=False)
        yield calls
        account_ready.disconnect(receiver)

    def test_the_code_check_sends_it_once_with_the_new_user(self, register, received):
        register()

        assert len(received) == 1
        sender, user = received[0]
        assert sender is User and user.email == "new@example.com"

    def test_the_receiver_sees_the_zone_already_stored(self, register):
        seen = []

        def receiver(sender, **kwargs):
            seen.append(Profile.objects.get(user=kwargs["user"]).timezone)

        account_ready.connect(receiver, weak=False)
        try:
            register(timezone="Europe/London")
        finally:
            account_ready.disconnect(receiver)

        assert seen == ["Europe/London"]

    def test_a_sign_up_waiting_for_its_code_or_refused_sends_nothing(self, signup, user, received):
        assert signup.register(email="waiting@example.com").status_code == 202  # no account yet
        assert signup.register(email=user.email).status_code == 202  # an address that has an account: a notice only
        assert signup.register(accept_terms=False).status_code == 400
        assert signup.verify("waiting@example.com", "000000").status_code == 400

        assert received == []

    def test_a_receiver_that_raises_does_not_undo_the_account(self, register):
        def broken(sender, **kwargs):
            raise RuntimeError("boom")

        account_ready.connect(broken, weak=False)
        try:
            response = register()
        finally:
            account_ready.disconnect(broken)

        assert response.status_code == 200 and User.objects.filter(email="new@example.com").exists()

    def test_signing_in_or_saving_the_profile_does_not_send_it(self, signed_in_client, received):
        signed_in_client.patch("/api/profile", {"notes": "x"}, format="json")

        assert received == []
