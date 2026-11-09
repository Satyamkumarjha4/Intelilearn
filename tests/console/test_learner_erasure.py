"""Unit under test: `GET` and `DELETE /api/console/learners/{id}/erasure` (`console.services.erasure.LearnerErasure`,
on top of `credits.erasure.AccountErasure`): deleting a learner's data from the console.

Why: a person can ask to be forgotten, and the console is where support acts on it. Deleting is the one thing in the
console that cannot be undone, so it has to say first exactly what it will do, ask the person at the keyboard to type
the account's email, refuse the accounts that must never be erased this way (your own, and staff), leave every other
learner's data alone, and leave a record that someone did it without keeping what it was meant to forget: the entry says
who erased which account (by id) and how much, and carries no name and no email.

Use cases:
- the preview says what would go and what would stay (lessons, quizzes, open reserves, credits written off, refresh
  tokens and sessions; the ledger rows, purchases and orders that are kept without identity) and changes nothing; it
  says when the account cannot be erased and why
- erasing needs the account's email typed (any case, spaces around it ignored); a wrong, empty or missing one is a 400
  that names the field and erases nothing
- erasing anonymises the account, deletes the lessons and quizzes, ends the sign-ins and writes the report; another
  learner's lessons, credits and sign-ins are untouched; the money that was kept shows no email or name
- exactly one change-log entry (`learner.erase`) is written, with counts, the target's id, and no name or email
- refused with a 409 and a code, and nothing changed: your own account, a staff account, an account already erased
- an unknown learner is a 404; anyone who is not staff, signed in or not, gets the 404 on both, and nothing changes
"""

import uuid

import pytest
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
from console.models import AuditEntry
from console.views.erasure import LearnerErasureView
from credits.erasure import AccountErasure
from credits.models import CreditTransaction
from lessons.erasure import LessonErasure
from lessons.models import Lesson
from lessons.services import LessonService
from payments.models import PaymentOrder
from quizzes.erasure import QuizErasure
from quizzes.models import QuickQuiz
from quizzes.services import QuickQuizService

pytestmark = pytest.mark.django_db

EMAIL, NAME = "ada@example.com", "Ada Lovelace"


class NoThreads:
    def delete(self, thread_ids):
        pass


class Silent:
    def publish(self, run_id, event):
        pass


@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    """The erasure without a real checkpoint store, as its own tests have it."""
    monkeypatch.setattr(
        LearnerErasureView,
        "erasure_factory",
        staticmethod(
            lambda trail: AccountErasure(
                lessons=LessonService(events=Silent(), erasure=LessonErasure(NoThreads())),
                quizzes=QuickQuizService(erasure=QuizErasure(NoThreads())),
                trail=trail,
            )
        ),
    )


def url(user):
    return f"/api/console/learners/{user.pk}/erasure"


def erase(client, user, email=EMAIL):
    body = {} if email is None else {"confirm_email": email}
    return client.delete(url(user), body, format="json")


@pytest.fixture
def lived(user, make_lesson, make_quiz, credits_on, payments):
    """A learner who has used the product: lessons, a quiz, credits, a sign-in and a payment."""
    make_lesson(topic="Binary search")
    make_lesson(topic="Graphs")
    make_quiz()
    credits_on.fund(user, 30, source="signup")
    RefreshToken.for_user(user)
    order = payments.buy("one_time", credits=50)
    payments.send("succeeded", order)
    return user


class TestThePreview:
    def test_it_says_what_would_go_and_what_would_stay_and_changes_nothing(self, staff_client, lived):
        before = AuditEntry.objects.count()

        body = staff_client.get(url(lived)).json()

        assert body["learner"] == {"id": str(lived.pk), "name": NAME, "email": EMAIL}
        assert (body["lessons"], body["quizzes"], body["refresh_tokens"]) == (2, 1, 1)
        assert body["credits_to_forfeit"] == 80 and body["orders_kept"] == 1 and body["ledger_rows_kept"] >= 2
        assert body["blocked"] == "" and body["erased"] is False
        assert Lesson.objects.filter(owner=lived).count() == 2 and AuditEntry.objects.count() == before

    def test_it_says_why_an_account_cannot_be_erased(self, staff_client, staff_user, other_user):
        User.objects.filter(pk=other_user.pk).update(is_staff=True)

        assert staff_client.get(url(staff_user)).json()["blocked"] == "cannot_erase_self"
        assert staff_client.get(url(other_user)).json()["blocked"] == "staff_account"

    def test_an_erased_account_says_so(self, staff_client, user):
        erase(staff_client, user)

        body = staff_client.get(url(user)).json()

        assert body["erased"] is True and body["blocked"] == "already_erased"

    def test_an_unknown_learner_is_a_404(self, staff_client):
        assert staff_client.get(f"/api/console/learners/{uuid.uuid4()}/erasure").status_code == 404


class TestErasing:
    def test_it_anonymises_the_account_and_deletes_what_the_learner_made(self, staff_client, lived):
        response = erase(staff_client, lived)

        body = response.json()
        assert response.status_code == 200 and body["erased"] is True
        assert (body["lessons"], body["quizzes"], body["credits_forfeited"], body["refresh_tokens"]) == (2, 1, 80, 1)
        lived.refresh_from_db()
        assert lived.email == f"deleted-{lived.pk}@erased.invalid" and lived.name == "" and not lived.is_active
        assert not Lesson.objects.filter(owner=lived).exists() and not QuickQuiz.objects.filter(owner=lived).exists()
        assert not OutstandingToken.objects.filter(user=lived).exists()

    def test_another_learners_data_and_sign_in_are_untouched(
        self, staff_client, lived, other_user, make_lesson, credits_on
    ):
        theirs = make_lesson(owner=other_user)
        credits_on.fund(other_user, 30, source="signup")
        token = RefreshToken.for_user(other_user)

        erase(staff_client, lived)

        assert Lesson.objects.filter(pk=theirs.pk).exists() and credits_on.balance(other_user) == 30
        assert OutstandingToken.objects.filter(jti=token["jti"]).exists()
        other_user.refresh_from_db()
        assert other_user.email == "grace@example.com" and other_user.is_active

    def test_the_money_is_kept_and_carries_no_identity(self, staff_client, lived):
        erase(staff_client, lived)

        assert PaymentOrder.objects.filter(user=lived).count() == 1
        assert CreditTransaction.objects.filter(user=lived, type="forfeit").count() == 1
        text = str(User.objects.filter(pk=lived.pk).values().get()) + str(list(CreditTransaction.objects.values()))
        assert EMAIL not in text and NAME not in text

    def test_one_change_log_entry_with_counts_and_no_name_or_email(self, staff_client, staff_user, lived):
        erase(staff_client, lived)

        entry = AuditEntry.objects.get(action="learner.erase")
        assert (entry.actor_email, entry.target_type, entry.target_id) == (staff_user.email, "learner", str(lived.pk))
        assert (
            entry.after == {"erased": True} and entry.before["lessons"] == 2 and entry.before["credits_forfeited"] == 80
        )
        assert EMAIL not in str(entry.before) and NAME not in str(entry.before) and EMAIL not in entry.target_id
        assert AuditEntry.objects.count() == 1

    def test_the_ledger_still_adds_up(self, staff_client, lived):
        from credits.audit import LedgerAudit

        erase(staff_client, lived)

        assert LedgerAudit().check(lived).ok

    @pytest.mark.parametrize("typed", [EMAIL.upper(), f"  {EMAIL}  ", "Ada@Example.com"])
    def test_the_email_may_be_typed_in_any_case_and_with_spaces(self, staff_client, user, typed):
        assert erase(staff_client, user, typed).status_code == 200


class TestRefusals:
    @pytest.mark.parametrize("typed", ["grace@example.com", "", "   ", None, "ada"])
    def test_a_wrong_empty_or_missing_email_is_a_400_that_names_the_field_and_erases_nothing(
        self, staff_client, lived, typed
    ):
        response = erase(staff_client, lived, typed)

        assert response.status_code == 400 and "confirm_email" in response.json()["fields"]
        lived.refresh_from_db()
        assert lived.email == EMAIL and Lesson.objects.filter(owner=lived).count() == 2
        assert not AuditEntry.objects.exists()

    def test_your_own_account_is_a_409(self, staff_client, staff_user):
        response = erase(staff_client, staff_user, staff_user.email)

        assert response.status_code == 409 and response.json()["code"] == "cannot_erase_self"
        staff_user.refresh_from_db()
        assert staff_user.is_active and staff_user.is_staff

    def test_a_staff_account_is_a_409_and_keeps_its_powers(self, staff_client, other_user):
        User.objects.filter(pk=other_user.pk).update(is_staff=True)

        response = erase(staff_client, other_user, other_user.email)

        assert response.status_code == 409 and response.json()["code"] == "staff_account"
        other_user.refresh_from_db()
        assert other_user.is_staff and other_user.is_active and not AuditEntry.objects.exists()

    def test_an_account_already_erased_is_a_409_and_writes_nothing_more(self, staff_client, user):
        erase(staff_client, user)

        again = erase(staff_client, user, f"deleted-{user.pk}@erased.invalid")

        assert again.status_code == 409 and again.json()["code"] == "already_erased"
        assert AuditEntry.objects.filter(action="learner.erase").count() == 1

    def test_an_unknown_learner_is_a_404(self, staff_client):
        response = staff_client.delete(
            f"/api/console/learners/{uuid.uuid4()}/erasure", {"confirm_email": EMAIL}, format="json"
        )

        assert response.status_code == 404


class TestWhoMayDoIt:
    @pytest.mark.parametrize("who", ["anonymous", "learner"])
    def test_anyone_who_is_not_staff_gets_a_404_on_both_and_nothing_changes(
        self, who, api_client, learner_client, lived, other_user
    ):
        client = api_client if who == "anonymous" else learner_client
        if who == "learner":
            client.get("/api/auth/csrf")

        read = client.get(url(other_user))
        wipe = client.delete(url(other_user), {"confirm_email": other_user.email}, format="json")

        for response in (read, wipe):
            assert response.status_code == 404 and response.json() == {"detail": "Not found.", "code": "not_found"}
        other_user.refresh_from_db()
        assert other_user.is_active and not AuditEntry.objects.exists()

    def test_it_is_all_one_transaction_for_the_change_and_its_entry(self, staff_client, user, monkeypatch):
        """If the entry cannot be written the account is not erased (they commit together)."""
        monkeypatch.setattr(
            "console.audit.AuditTrail.record", lambda self, *a, **k: (_ for _ in ()).throw(RuntimeError("log down"))
        )

        with pytest.raises(RuntimeError):
            erase(staff_client, user)

        user.refresh_from_db()
        assert user.email == EMAIL and user.deleted_at is None
