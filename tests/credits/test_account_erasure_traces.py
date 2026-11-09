"""Unit under test: what `credits.erasure.AccountErasure` removes besides the learner's lessons and quizzes (phase 10.9
follow-up: deleting a learner from the console), and `UserDataMap`, the list of every table that points at a user.

Why: "delete everything of this person" is only true if it reaches the places a person leaves a trace without making a
lesson: the refresh tokens that keep a sign-in alive, the sessions of the Django admin, the admin's own log of what was
done to their account (which quotes their name and email), and the free-text reasons staff typed in the change log when
they moved the learner's credits. Whatever is kept (the money, because it is append-only and the law asks for it) must
carry no identity. And a table added next year that points at a user must not slip past all of this unseen.

Use cases:
- the learner's refresh tokens (and the blacklist rows that hang on them) are deleted, other learners' are not
- the learner's admin sessions are deleted, other people's are not
- the Django admin's log rows about the learner's account and wallet are deleted (they quote the name and email); log
  rows about anything else stay
- change-log entries about the learner lose the free-text reason, keep the amounts and the action, and no other
  entry is changed
- the report counts each of these, a dry run counts them and changes nothing, and erasing again does nothing more
- when a change log is given, the erasure writes one entry for it (`learner.erase`) inside the same transaction,
  carrying counts and no name, no email
- `UserDataMap` names what happens to every table that points at a user (erased, scrubbed, kept without identity or
  links cleared), has no stale rows, and fails if a table is added that it does not mention
"""

import pytest
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.contenttypes.models import ContentType
from django.contrib.sessions.models import Session
from django.test import Client
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
from console.audit import AuditTrail
from console.models import AuditEntry
from credits.erasure import AccountErasure, UserDataMap
from credits.models import Wallet
from lessons.erasure import LessonErasure
from lessons.services import LessonService
from quizzes.erasure import QuizErasure
from quizzes.services import QuickQuizService

pytestmark = pytest.mark.django_db

EMAIL, NAME = "ada@example.com", "Ada Lovelace"


class NoThreads:
    def delete(self, thread_ids):
        pass


class Silent:
    def publish(self, run_id, event):
        pass


@pytest.fixture
def erasure(ledger):
    return AccountErasure(
        ledger=ledger,
        lessons=LessonService(events=Silent(), erasure=LessonErasure(NoThreads())),
        quizzes=QuickQuizService(erasure=QuizErasure(NoThreads())),
    )


@pytest.fixture
def staff(db):
    return User.objects.create_user("root@example.com", password="x-staff-pass-1", name="Root", is_staff=True)


def session_of(user) -> str:
    client = Client()
    client.force_login(user)
    return client.session.session_key


class TestSignInsAreEnded:
    def test_refresh_tokens_and_their_blacklist_rows_go_and_others_stay(self, erasure, user, other_user):
        mine, theirs = RefreshToken.for_user(user), RefreshToken.for_user(other_user)
        mine.blacklist()

        report = erasure.erase(user)

        assert not OutstandingToken.objects.filter(user=user).exists() and not BlacklistedToken.objects.exists()
        assert OutstandingToken.objects.filter(jti=theirs["jti"]).exists()
        assert report.tokens == 1

    def test_admin_sessions_go_and_other_peoples_stay(self, erasure, user, other_user):
        mine, theirs = session_of(user), session_of(other_user)

        report = erasure.erase(user)

        assert not Session.objects.filter(session_key=mine).exists()
        assert Session.objects.filter(session_key=theirs).exists() and report.sessions == 1


class TestTracesInTheLogs:
    def log(self, actor, obj, text):
        return LogEntry.objects.create(
            user=actor, content_type=ContentType.objects.get_for_model(type(obj)), object_id=str(obj.pk),
            object_repr=text, action_flag=CHANGE, change_message="[]",
        )  # fmt: skip

    def test_admin_log_rows_about_the_account_and_wallet_go_and_others_stay(self, erasure, user, other_user, staff):
        Wallet.objects.create(user=user, created_at=user.date_joined)
        about_user = self.log(staff, user, f"{NAME} <{EMAIL}>")
        about_wallet = self.log(staff, user.wallet, f"Wallet of {EMAIL}")
        about_other = self.log(staff, other_user, "Grace")

        report = erasure.erase(user)

        assert not LogEntry.objects.filter(pk__in=[about_user.pk, about_wallet.pk]).exists()
        assert LogEntry.objects.filter(pk=about_other.pk).exists() and report.admin_log == 2

    def test_change_log_entries_about_the_learner_lose_the_free_text_but_keep_the_numbers(
        self, erasure, user, staff, other_user
    ):
        trail = AuditTrail(staff)
        mine = trail.record(
            "credits.adjust", "wallet", user.pk,
            before={"balance": 3}, after={"balance": 8, "amount": 5, "reason": f"Gift to {NAME}"},
        )  # fmt: skip
        elsewhere = trail.record("credits.adjust", "wallet", other_user.pk, after={"reason": "Gift to Grace"})
        unrelated = trail.record("model.update", "model", 3, after={"reason": "kept"})

        report = erasure.erase(user)

        mine.refresh_from_db()
        assert mine.after == {"balance": 8, "amount": 5} and mine.before == {"balance": 3}
        assert (mine.action, mine.target_id) == ("credits.adjust", str(user.pk))
        for kept in (elsewhere, unrelated):
            before = kept.after
            kept.refresh_from_db()
            assert kept.after == before
        assert report.audit_scrubbed == 1 and NAME not in str(
            AuditEntry.objects.filter(target_id=str(user.pk)).values()
        )


class TestTheReportAndTheTrail:
    def test_a_dry_run_counts_the_traces_and_changes_nothing(self, erasure, user):
        RefreshToken.for_user(user)
        session = session_of(user)

        report = erasure.erase(user, dry_run=True)

        assert (report.tokens, report.sessions) == (1, 1) and report.dry_run
        assert (
            OutstandingToken.objects.filter(user=user).exists() and Session.objects.filter(session_key=session).exists()
        )
        user.refresh_from_db()
        assert user.deleted_at is None

    def test_erasing_again_does_nothing_more(self, erasure, user):
        erasure.erase(user)

        again = erasure.erase(user)

        assert again.already_erased and (again.tokens, again.sessions, again.admin_log) == (0, 0, 0)

    def test_a_trail_gets_one_entry_with_counts_and_no_identity(self, ledger, user, staff):
        erasure = AccountErasure(
            ledger=ledger,
            lessons=LessonService(events=Silent(), erasure=LessonErasure(NoThreads())),
            quizzes=QuickQuizService(erasure=QuizErasure(NoThreads())),
            trail=AuditTrail(staff),
        )
        RefreshToken.for_user(user)

        erasure.erase(user)

        entry = AuditEntry.objects.get(action="learner.erase")
        assert (entry.actor_email, entry.target_type, entry.target_id) == (staff.email, "learner", str(user.pk))
        assert entry.after == {"erased": True} and entry.before["refresh_tokens"] == 1
        assert EMAIL not in str(entry.before) + str(entry.after) and NAME not in str(entry.before) + str(entry.after)

    def test_without_a_trail_nothing_is_written_to_the_change_log(self, erasure, user):
        erasure.erase(user)

        assert not AuditEntry.objects.exists()


class TestEveryTableThatPointsAtAUserIsAccountedFor:
    def relations(self):
        return {
            f"{r.related_model._meta.label}.{r.field.name}"
            for r in User._meta.get_fields(include_hidden=True)
            if r.auto_created and not r.concrete and r.related_model
        }

    def test_every_relation_to_a_user_is_named_and_none_is_stale(self):
        named = set(UserDataMap.TABLES)

        assert self.relations() - named == set(), (
            "a table points at a user and UserDataMap does not say what happens to it"
        )
        assert named - self.relations() == set(), "UserDataMap names a table that no longer points at a user"

    def test_each_row_has_a_known_fate_and_a_reason(self):
        for table, (fate, why) in UserDataMap.TABLES.items():
            assert fate in UserDataMap.FATES, table
            assert len(why) > 20, table

    def test_the_places_with_no_relation_are_named_too(self):
        assert {
            "sessions.Session",
            "admin.LogEntry (about the account)",
            "console.AuditEntry (about the learner)",
        } <= set(UserDataMap.OUTSIDE)

    def test_kept_rows_are_only_the_money(self):
        kept = {table for table, (fate, _) in UserDataMap.TABLES.items() if fate == UserDataMap.KEPT}

        assert all(table.split(".")[0] in {"credits", "payments", "admin", "console"} for table in kept)
