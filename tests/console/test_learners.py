"""Unit under test: `console.services.learners` (`LearnerQuery`, `LearnerSummary`) behind `GET /api/console/learners`.

Why: when someone writes in about a broken lesson, this is where their account is found. It must show who is using
Socra and how much, never what they wrote about themselves (profile notes) or anything that could sign in as them, and
it is read-only: changing an account stays in the Django admin.

Use cases:
- a learner is listed with their profile choices, how many lessons they have, when they were last active (their latest
  lesson activity or sign-in), whether their profile is complete, and whether they are staff
- the list is newest members first, in pages, and can be searched by name or email
- a summary counts all learners, how many were active in the last 7 days, how many finished their profile and how
  many are staff, whatever the search
- a learner's row says whether their email is verified, who vouched for it (`verification_source`) and whether the email
  is locked right now (a lock that has ended is not a lock)
- `?verification=` keeps only the learners that need a look: `unverified` (the email was never proved), `legacy` (an
  account from before verification, verified by migration and never proved) or `locked` (too many dead codes lately);
  it combines with the search, survives paging, counts only open accounts (not closed or erased ones), and an unknown
  value is a `400` naming the field
- the summary also counts `unverified`, `legacy` and `locked` over every learner, whatever the search or the filter
- notes, password hashes and tokens are never in a response
- the list runs the same number of queries for three learners and for thirty
- it is read-only, and not open to a learner
"""

from datetime import timedelta

import pytest

from accounts.models import Profile, User
from lessons.models import Lesson

pytestmark = pytest.mark.django_db

D = timedelta(days=1)


@pytest.fixture
def people(db, now, user, other_user, staff_user):
    """Ada (complete profile, a lesson, signed in 2 days ago), Grace (empty profile, never signed in), the staff."""
    User.objects.filter(pk=user.pk).update(date_joined=now - 10 * D, last_login=now - 2 * D)
    User.objects.filter(pk=other_user.pk).update(date_joined=now - 5 * D)
    User.objects.filter(pk=staff_user.pk).update(date_joined=now - 20 * D, last_login=now - 30 * D)
    Profile.objects.filter(user=user).update(
        education_level="undergraduate", grade_or_year="2nd year", learning_preference="visual", goal="exam_prep",
        preferred_language="hi", notes="I have a private worry about this exam.",
    )  # fmt: skip
    lesson = Lesson.objects.create(owner=user, topic="Graphs")
    Lesson.objects.filter(pk=lesson.pk).update(updated_at=now - 1 * D)
    return user, other_user, staff_user


def test_a_learner_row_shows_their_profile_activity_and_standing(staff_client, people, now):
    ada, _, _ = people

    rows = {r["email"]: r for r in staff_client.get("/api/console/learners").json()["results"]}

    assert rows["ada@example.com"] == {
        "id": str(ada.id), "name": "Ada Lovelace", "email": "ada@example.com", "education_level": "undergraduate",
        "grade_or_year": "2nd year", "goal": "exam_prep", "preferred_language": "hi", "lessons_count": 1,
        "last_active_at": "2026-03-14T12:00:00Z", "profile_complete": True, "is_staff": False,
        "joined_at": "2026-03-05T12:00:00Z", "email_verified": True, "verification_source": "operator",
        "email_locked": False,
    }  # fmt: skip
    grace = rows["grace@example.com"]
    assert (grace["lessons_count"], grace["last_active_at"], grace["profile_complete"]) == (0, None, False)
    assert grace["education_level"] == "" and grace["preferred_language"] == "en"


def test_last_activity_is_the_later_of_the_latest_lesson_and_the_last_sign_in(staff_client, people, now):
    ada, _, staff = people
    User.objects.filter(pk=ada.pk).update(last_login=now - 1 * timedelta(hours=1))  # after the lesson's update

    rows = {r["email"]: r for r in staff_client.get("/api/console/learners").json()["results"]}

    assert rows["ada@example.com"]["last_active_at"] == "2026-03-15T11:00:00Z"
    assert rows[staff.email]["last_active_at"] == "2026-02-13T12:00:00Z"  # signed in 30 days ago, no lessons


def test_members_are_listed_newest_first_in_pages(staff_client, people):
    first = staff_client.get("/api/console/learners?page_size=2").json()
    second = staff_client.get(first["next"]).json()

    assert [r["email"] for r in first["results"]] == ["grace@example.com", "ada@example.com"]
    assert [r["email"] for r in second["results"]] == ["root@example.com"]


EVERYONE = {"ada@example.com", "grace@example.com", "root@example.com"}
#: the three sign-in counts when nobody needs a look
NO_ATTENTION = {"unverified": 0, "legacy": 0, "locked": 0}


@pytest.mark.parametrize(
    ("query", "emails"),
    [("ada", {"ada@example.com"}), ("HOPPER", {"grace@example.com"}), ("example.com", EVERYONE), ("zzz", set())],
)
def test_learners_can_be_searched_by_name_or_email(staff_client, people, query, emails):
    rows = staff_client.get(f"/api/console/learners?q={query}").json()["results"]

    assert {r["email"] for r in rows} == emails


def test_the_summary_counts_everyone_whatever_the_search(staff_client, people):
    everything = staff_client.get("/api/console/learners").json()["summary"]
    searched = staff_client.get("/api/console/learners?q=ada").json()["summary"]

    # Ada was active yesterday, Grace never, the staff user a month ago; only Ada finished her profile; one is staff
    assert everything == {"total": 3, "active_7d": 1, "profile_complete": 1, "staff": 1, **NO_ATTENTION}
    assert searched == everything


def test_notes_and_credentials_are_never_in_the_response(staff_client, people):
    response = staff_client.get("/api/console/learners")

    text = response.content.decode()
    assert "private worry" not in text and "password" not in text and "pbkdf2" not in text


def test_a_member_without_a_profile_row_is_listed_as_incomplete(staff_client, people):
    Profile.objects.filter(user__email="grace@example.com").delete()

    rows = {r["email"]: r for r in staff_client.get("/api/console/learners").json()["results"]}

    assert rows["grace@example.com"]["profile_complete"] is False and rows["grace@example.com"]["education_level"] == ""


def test_the_list_query_count_does_not_grow_with_the_learners(staff_client, people, count_queries):
    def fetch():
        assert staff_client.get("/api/console/learners?page_size=100").status_code == 200

    few = count_queries(fetch)
    for index in range(30):
        member = User.objects.create_user(f"member{index}@example.com", password="x" * 12, name=f"Member {index}")
        Lesson.objects.create(owner=member, topic="t")

    assert count_queries(fetch) == few


def test_the_learners_list_is_read_only(staff_client, people):
    ada, _, _ = people

    assert staff_client.post("/api/console/learners", {}, format="json").status_code == 405
    assert staff_client.patch(f"/api/console/learners/{ada.id}", {}, format="json").status_code == 404


def test_a_learner_cannot_see_other_learners(learner_client):
    assert learner_client.get("/api/console/learners").status_code == 404


# --- sign-in: verification column, filter and counts ---


@pytest.fixture
def attention(people, now):
    """Beyond the three in `people` (every one verified): an unverified one, a legacy one, one with a live lock, one
    whose lock has ended, a closed unverified account and an erased one. Returns them by name."""
    from accounts.models import EmailLock

    def make(name, **fields):
        user = User.objects.create_user(f"{name}@example.com", password="x" * 12, name=name.title())
        User.objects.filter(pk=user.pk).update(**fields)
        return User.objects.get(pk=user.pk)

    found = {
        "newbie": make("newbie"),
        "legacy": make("legacy", email_verified_at=now - 90 * D, email_verification_source="legacy"),
        "stuck": make("stuck"),
        "past": make("past", email_verified_at=now - D, email_verification_source="code"),
        "closed": make("closed", is_active=False),
        "gone": make("gone", is_active=False, deleted_at=now - D),
    }
    EmailLock.objects.create(email_canonical="stuck@example.com", locked_until=now + timedelta(minutes=30), strikes=3)
    EmailLock.objects.create(email_canonical="past@example.com", locked_until=now - timedelta(minutes=30), strikes=3)
    EmailLock.objects.create(email_canonical="closed@example.com", locked_until=now + timedelta(minutes=30), strikes=3)
    return found


def emails(client, query=""):
    return {r["email"] for r in client.get(f"/api/console/learners{query}").json()["results"]}


def test_a_row_says_whether_the_email_is_verified_who_vouched_and_whether_it_is_locked(staff_client, attention):
    rows = {r["email"]: r for r in staff_client.get("/api/console/learners?page_size=50").json()["results"]}

    def say(name):
        row = rows[f"{name}@example.com"]
        return row["email_verified"], row["verification_source"], row["email_locked"]

    assert say("newbie") == (False, "", False)
    assert say("legacy") == (True, "legacy", False)
    assert say("stuck") == (False, "", True)  # unverified and locked
    assert say("past") == (True, "code", False)  # the lock ended 30 minutes ago


def test_unverified_keeps_open_accounts_whose_email_was_never_proved(staff_client, attention):
    assert emails(staff_client, "?verification=unverified") == {"newbie@example.com", "stuck@example.com"}


def test_legacy_keeps_open_accounts_verified_by_the_migration(staff_client, attention):
    assert emails(staff_client, "?verification=legacy") == {"legacy@example.com"}


def test_locked_keeps_open_accounts_with_a_live_lock_only(staff_client, attention):
    assert emails(staff_client, "?verification=locked") == {"stuck@example.com"}  # not past, not the closed one


def test_the_filter_combines_with_the_search_and_survives_paging(staff_client, attention):
    searched = emails(staff_client, "?verification=unverified&q=newbie")
    broad = emails(staff_client, "?verification=unverified&q=example.com")  # matches everyone; the filter still cuts
    first = staff_client.get("/api/console/learners?verification=unverified&page_size=1").json()
    second = staff_client.get(first["next"]).json()

    assert searched == {"newbie@example.com"}
    assert broad == {"newbie@example.com", "stuck@example.com"}
    assert len(first["results"]) == 1 and len(second["results"]) == 1 and second["next"] is None
    assert {first["results"][0]["email"], second["results"][0]["email"]} == {"newbie@example.com", "stuck@example.com"}


def test_an_empty_filter_is_everyone_and_an_unknown_one_is_a_400_naming_the_field(staff_client, attention):
    everyone = emails(staff_client, "?verification=")
    refused = staff_client.get("/api/console/learners?verification=verified")

    assert "newbie@example.com" in everyone and "gone@example.com" in everyone
    assert refused.status_code == 400 and "verification" in refused.json()["fields"]


def test_the_summary_counts_the_three_over_everyone_whatever_the_search_or_the_filter(staff_client, attention):
    expected = {"unverified": 2, "legacy": 1, "locked": 1}

    plain = staff_client.get("/api/console/learners").json()["summary"]
    searched = staff_client.get("/api/console/learners?q=ada&verification=legacy").json()["summary"]

    assert {k: plain[k] for k in expected} == expected and searched == plain


def test_a_locked_unverified_account_is_counted_in_both(staff_client, attention):
    summary = staff_client.get("/api/console/learners").json()["summary"]

    assert emails(staff_client, "?verification=unverified") >= emails(staff_client, "?verification=locked")
    assert summary["unverified"] == 2 and summary["locked"] == 1  # "stuck" is one of each


def test_the_filter_runs_the_same_number_of_queries_for_few_and_many(staff_client, attention, count_queries):
    def fetch():
        assert staff_client.get("/api/console/learners?verification=unverified&page_size=100").status_code == 200

    few = count_queries(fetch)
    for index in range(20):
        User.objects.create_user(f"more{index}@example.com", password="x" * 12, name=f"More {index}")

    assert count_queries(fetch) == few
