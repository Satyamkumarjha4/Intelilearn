"""Unit under test: `credits.erasure.AccountErasure` and `manage.py erase_account` (credits plan P5, phase 10.3).

Why: a person can ask us to delete their account, and the ledger is append-only and the user is a protected key, so the
account cannot simply be deleted. Instead the row stays and everything personal goes: the name, the email, the
profile, the
lessons, the quizzes, the checkpoints, the sign-in. What remains is an anonymous record of money, and it has to add up:
unspent credits are written off on the ledger, held credits are released first, and nothing is ever edited.

Use cases:
- erasing anonymises the user in place: email and name scrubbed, password unusable, inactive, not staff, marked deleted,
  and the profile emptied (education, notes, zone and all)
- the learner's lessons and quizzes are gone, with their checkpoints and model calls; other learners' are not
- streak days and the cached streak are gone
- open holds are released first, then the balance is forfeited in one row equal to what was left; the ledger still
  equals the
  buckets after erasure; no ledger row was edited
- no trace of the original email or name is left in the user, the profile or the ledger rows
- the account can no longer sign in or use a session it already had
- a learner who never had credits is erased with no ledger row
- a staff account loses its powers
- erasing again changes nothing and says so; a learner is erased even if a previous attempt stopped half way
- the dry run reports what it would do and changes nothing
- the command erases by email or id, with a dry run, and refuses an unknown learner
"""

from io import StringIO
from uuid import uuid4

import pytest
from django.core.management import CommandError, call_command
from django.db.models import Sum

from accounts.models import Profile, User
from credits.audit import LedgerAudit
from credits.earning.signup import SignupGrant
from credits.erasure import AccountErasure
from credits.models import CreditBucket, CreditHold, CreditTransaction, StreakDay, StreakState
from lessons.erasure import LessonErasure
from lessons.models import Lesson
from lessons.services import LessonService
from llm_registry.models import ModelCall
from quizzes.erasure import QuizErasure
from quizzes.models import QuickQuiz
from quizzes.services import QuickQuizService

pytestmark = pytest.mark.django_db

EMAIL, NAME = "ada@example.com", "Ada Lovelace"


class FakeThreads:
    def __init__(self):
        self.deleted: list[str] = []

    def delete(self, thread_ids):
        self.deleted.extend(thread_ids)


class Silent:
    def publish(self, run_id, event):
        pass


@pytest.fixture
def threads():
    return FakeThreads()


@pytest.fixture
def erasure(ledger, threads):
    return AccountErasure(
        ledger=ledger,
        lessons=LessonService(events=Silent(), erasure=LessonErasure(threads)),
        quizzes=QuickQuizService(erasure=QuizErasure(threads)),
    )


@pytest.fixture
def lived(user, make_lesson, make_quiz, give, ledger, clock):
    """A learner who has used the product: a profile, lessons, a quiz, credits, a reserve and a streak."""
    Profile.objects.filter(user=user).update(
        education_level="undergraduate", grade_or_year="2nd year", field_of_study="Computer Science",
        learning_preference="hands_on", goal="exam_prep", notes="I know arrays already.", timezone="Europe/London",
    )  # fmt: skip
    User.objects.filter(pk=user.pk).update(last_login=clock.now())
    user.refresh_from_db()
    lessons = [make_lesson(topic="Binary search"), make_lesson(topic="Graphs")]
    quiz = make_quiz()
    for lesson in lessons:
        ModelCall.objects.create(
            lesson_id=lesson.id, node_key="n", provider_key="p", model_name="m", attempt=1, fallback_index=0,
            status="ok", latency_ms=1,
        )  # fmt: skip
    SignupGrant(ledger=ledger).on_account_ready(user)
    give(user, 12, days=60)
    ledger.place_hold(user, 5, "lesson.create", "h1", subject_kind="lesson", subject_id=lessons[0].id)
    StreakDay.objects.create(user=user, local_date=clock.now().date(), kind="active", created_at=clock.now())
    StreakState.objects.create(user=user, current_streak=1, longest_streak=1, updated_at=clock.now())
    return user, lessons, quiz


class TestWhatIsErased:
    def test_the_user_is_anonymised_in_place(self, erasure, lived, clock):
        user, *_ = lived
        original_id = user.pk

        erasure.erase(user)

        user.refresh_from_db()
        assert user.pk == original_id
        assert user.email == f"deleted-{original_id}@erased.invalid" and user.name == ""
        assert not user.has_usable_password() and user.is_active is False
        assert (user.is_staff, user.is_superuser, user.last_login) == (False, False, None)
        assert user.deleted_at == clock.now()

    def test_the_profile_is_emptied(self, erasure, lived):
        user, *_ = lived

        erasure.erase(user)

        profile = Profile.objects.get(user=user)
        assert (profile.education_level, profile.grade_or_year, profile.field_of_study) == ("", "", "")
        assert (profile.learning_preference, profile.goal, profile.notes) == ("", "", "")
        assert (profile.timezone, profile.timezone_changed_at, profile.preferred_language) == ("", None, "en")

    def test_lessons_quizzes_checkpoints_and_model_calls_go_and_other_learners_stay(
        self, erasure, lived, threads, other_user, make_lesson
    ):
        user, lessons, quiz = lived
        theirs = make_lesson(owner=other_user)

        erasure.erase(user)

        assert not Lesson.objects.filter(owner=user).exists() and not QuickQuiz.objects.filter(owner=user).exists()
        assert not ModelCall.objects.filter(lesson_id__in=[lesson.id for lesson in lessons]).exists()
        assert {str(lesson.id) for lesson in lessons} <= set(threads.deleted) and str(quiz.id) in threads.deleted
        assert Lesson.objects.filter(pk=theirs.pk).exists() and str(theirs.id) not in threads.deleted

    def test_streak_days_and_the_cached_streak_go(self, erasure, lived):
        user, *_ = lived

        erasure.erase(user)

        assert not StreakDay.objects.filter(user=user).exists() and not StreakState.objects.filter(user=user).exists()

    def test_no_trace_of_the_original_email_or_name_is_left(self, erasure, lived):
        user, *_ = lived

        erasure.erase(user)

        leftovers = [
            str(User.objects.filter(pk=user.pk).values().get()),
            str(Profile.objects.filter(user=user).values().get()),
        ]
        leftovers += [
            str(row.meta) + row.action + row.subject_kind for row in CreditTransaction.objects.filter(user=user)
        ]
        leftovers += [str(h.lines) + h.action for h in CreditHold.objects.filter(user=user)]
        for text in leftovers:
            assert EMAIL not in text and NAME not in text and "Lovelace" not in text and "arrays" not in text

    def test_the_account_can_no_longer_sign_in_or_use_a_session_it_had(
        self, erasure, lived, signed_in_client, api_client
    ):
        user, *_ = lived
        assert signed_in_client.get("/api/auth/me").status_code == 200

        erasure.erase(user)

        assert signed_in_client.get("/api/auth/me").status_code == 401
        login = api_client.post(
            "/api/auth/login", {"email": EMAIL, "password": "correct-horse-battery-staple"}, format="json"
        )
        assert login.status_code == 401

    def test_a_staff_account_loses_its_powers(self, erasure, user):
        User.objects.filter(pk=user.pk).update(is_staff=True, is_superuser=True)
        user.refresh_from_db()

        erasure.erase(user)

        user.refresh_from_db()
        assert (user.is_staff, user.is_superuser, user.is_active) == (False, False, False)


class TestTheMoney:
    def test_open_holds_are_released_then_the_balance_is_forfeited_in_one_row(self, erasure, lived, ledger):
        user, lessons, _ = lived
        assert ledger.reserved(user) == 5
        balance_before = ledger.balance(user)  # 30 + 12 - 5 = 37

        report = erasure.erase(user)

        rows = list(CreditTransaction.objects.filter(user=user).order_by("id"))
        assert [r.type for r in rows][-2:] == ["release", "forfeit"]
        release, forfeit = rows[-2], rows[-1]
        assert release.amount == 5 and forfeit.amount == -(balance_before + 5)
        assert forfeit.balance_after == 0 and forfeit.idempotency_key == f"forfeit:{user.pk}"
        assert report.forfeited == balance_before + 5 and report.released_holds == 1
        assert ledger.balance(user) == 0 and ledger.reserved(user) == 0

    def test_the_ledger_still_equals_the_buckets_and_no_row_was_edited(self, erasure, lived):
        user, *_ = lived
        before = list(CreditTransaction.objects.filter(user=user).order_by("id").values())

        erasure.erase(user)

        after = list(CreditTransaction.objects.filter(user=user).order_by("id").values())
        assert after[: len(before)] == before  # every earlier row is exactly as it was
        assert LedgerAudit().check(user).ok
        assert CreditBucket.objects.filter(user=user).aggregate(total=Sum("amount_remaining"))["total"] == 0

    def test_a_learner_who_never_had_credits_is_erased_with_no_ledger_row(self, erasure, user):
        erasure.erase(user)

        assert not CreditTransaction.objects.filter(user=user).exists()
        user.refresh_from_db()
        assert user.deleted_at is not None

    def test_the_forfeit_equals_the_balance_even_with_a_lapsed_bucket(self, erasure, lived, ledger, clock):
        user, *_ = lived
        clock.advance(days=61)  # the 12 credits with a 60-day life have lapsed

        report = erasure.erase(user)

        assert (
            report.forfeited == 35 and ledger.balance(user) == 0
        )  # 30 that never lapse, 5 given back to a refund bucket and LedgerAudit().check(user).ok


class TestRepeatingAndPlanning:
    def test_erasing_again_changes_nothing_and_says_so(self, erasure, lived):
        user, *_ = lived
        erasure.erase(user)
        rows = CreditTransaction.objects.count()

        again = erasure.erase(user)

        assert again.already_erased is True and CreditTransaction.objects.count() == rows

    def test_a_previous_attempt_that_stopped_half_way_is_finished(self, ledger, threads, lived):
        user, lessons, _ = lived

        class Fails(LessonService):
            def delete(self, lesson):
                raise RuntimeError("the checkpoint store is down")

        broken = AccountErasure(
            ledger=ledger, lessons=Fails(events=Silent()), quizzes=QuickQuizService(erasure=QuizErasure(threads))
        )
        with pytest.raises(RuntimeError):
            broken.erase(user)
        user.refresh_from_db()
        assert user.deleted_at is None and user.is_active  # nothing was anonymised

        fine = AccountErasure(
            ledger=ledger,
            lessons=LessonService(events=Silent(), erasure=LessonErasure(threads)),
            quizzes=QuickQuizService(erasure=QuizErasure(threads)),
        )
        report = fine.erase(user)

        user.refresh_from_db()
        assert report.already_erased is False and user.deleted_at is not None
        assert not Lesson.objects.filter(owner=user).exists()
        assert CreditTransaction.objects.filter(idempotency_key=f"forfeit:{user.pk}").count() == 1

    def test_the_dry_run_reports_and_changes_nothing(self, erasure, lived, ledger, threads):
        user, lessons, quiz = lived
        rows = CreditTransaction.objects.count()

        report = erasure.erase(user, dry_run=True)

        assert report.dry_run is True and report.lessons == 2 and report.quizzes == 1
        assert (report.released_holds, report.forfeited) == (1, 42)
        user.refresh_from_db()
        assert user.email == EMAIL and user.deleted_at is None and user.is_active
        assert Lesson.objects.filter(owner=user).count() == 2 and CreditTransaction.objects.count() == rows
        assert threads.deleted == [] and StreakDay.objects.filter(user=user).exists()


class TestTheCommand:
    def run(self, *args):
        out = StringIO()
        call_command("erase_account", *args, stdout=out)
        return out.getvalue()

    @pytest.fixture(autouse=True)
    def no_checkpoint_tables(self, monkeypatch):
        monkeypatch.setattr("lessons.erasure.CheckpointThreads.delete", lambda self, ids: None)

    def test_it_erases_by_email(self, user, give):
        give(user, 5)

        out = self.run(EMAIL)

        user.refresh_from_db()
        assert user.deleted_at is not None and "Erased" in out and "5 credits forfeited" in out

    def test_it_erases_by_id(self, user):
        self.run(str(user.pk))

        user.refresh_from_db()
        assert user.deleted_at is not None

    def test_the_dry_run_says_what_it_would_do_and_does_nothing(self, user, give):
        give(user, 5)

        out = self.run(EMAIL, "--dry-run")

        user.refresh_from_db()
        assert "Dry run" in out and "would" in out and user.deleted_at is None and user.email == EMAIL

    def test_an_unknown_learner_is_an_error(self):
        with pytest.raises(CommandError, match="No learner"):
            self.run("nobody@example.com")
        with pytest.raises(CommandError, match="No learner"):
            self.run(str(uuid4()))

    def test_an_erased_learner_is_reported_as_already_erased(self, user):
        self.run(EMAIL)

        assert "already erased" in self.run(str(user.pk)).lower()
