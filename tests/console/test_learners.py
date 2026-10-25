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
        "joined_at": "2026-03-05T12:00:00Z",
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
    assert everything == {"total": 3, "active_7d": 1, "profile_complete": 1, "staff": 1}
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
