"""Unit under test: `credits.audit.LedgerAudit` and the `credits_audit` command, which check the equation of the ledger
(credits plan T4): the sum of a learner's rows equals the sum of their buckets, and the last row's `balance_after` is
that
same number.

Why: if a bug ever made or lost a credit, this is how we would find out. It has to say nothing about healthy books, name
the learner whose books are off, and be usable by an operator (and by the hourly job later) for one learner or all.

Use cases:
- books made only through the ledger have no break, for one learner and for all, including a learner with no movement
- a bucket changed behind the ledger's back is a break that names the learner, both sums and what is wrong
- a ledger row that is missing from the buckets' story (a row with no bucket change) is a break; so is a last row whose
  running balance is not the sum
- a bucket with no ledger row at all is a break; breaks of one learner do not hide in a clean learner's report
- the command prints a line per break and exits non-zero when there is one, prints how many learners it checked when
  there is none, and can be pointed at one learner by id or by email
"""

from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from django.db import connection

from credits.audit import LedgerAudit
from credits.models import CreditBucket

pytestmark = pytest.mark.django_db


def break_the_books(user):
    """Take the credits out of a bucket without telling the ledger (what a bug or a hand edit would do)."""
    CreditBucket.objects.filter(user=user).update(amount_remaining=0)


def test_books_made_through_the_ledger_have_no_break(ledger, give, user, other_user):
    give(user, 10)
    ledger.debit(user, 4, "x", "d")
    give(other_user, 5, days=3)

    assert LedgerAudit().check(user).ok
    report = LedgerAudit().check_all()
    assert report.ok and report.checked == 2 and report.breaks == ()


def test_a_learner_with_no_movement_has_nothing_to_break(user):
    report = LedgerAudit().check(user)

    assert report.ok and report.checked == 1


def test_a_bucket_changed_behind_the_ledgers_back_names_the_learner_and_both_sums(ledger, give, user, other_user):
    give(user, 10)
    give(other_user, 10)
    CreditBucket.objects.filter(user=user).update(amount_remaining=7)

    report = LedgerAudit().check_all()

    (broken,) = report.breaks
    assert broken.user_id == user.pk and (broken.ledger_sum, broken.bucket_sum) == (10, 7)
    assert any("bucket" in problem for problem in broken.problems)
    assert not report.ok and report.checked == 2


def test_a_last_row_whose_running_balance_is_not_the_sum_is_a_break(ledger, give, user):
    give(user, 10)
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO credits_credittransaction (user_id, type, amount, balance_after, action, subject_kind, "
            "bucket_allocations, idempotency_key, meta, created_at) "
            "VALUES (%s, 'debit', 0, 99, '', '', '[]', 'crooked', '{}', now())",
            [user.pk],
        )

    (broken,) = LedgerAudit().check(user).breaks

    assert broken.last_balance == 99 and broken.ledger_sum == 10
    assert any("running balance" in problem for problem in broken.problems)


def test_a_bucket_with_no_ledger_row_is_a_break(ledger, user):
    from datetime import UTC, datetime

    CreditBucket.objects.create(
        user=user, source="signup", amount_granted=5, amount_remaining=5, created_at=datetime(2026, 1, 1, tzinfo=UTC)
    )

    (broken,) = LedgerAudit().check_all().breaks

    assert (broken.user_id, broken.ledger_sum, broken.bucket_sum) == (user.pk, 0, 5)


def test_one_break_does_not_hide_another_or_a_clean_learner(ledger, give, user, other_user):
    give(user, 10)
    give(other_user, 10)
    break_the_books(user)
    break_the_books(other_user)

    report = LedgerAudit().check_all()

    assert {b.user_id for b in report.breaks} == {user.pk, other_user.pk}


class TestTheCommand:
    def run(self, *args):
        out = StringIO()
        call_command("credits_audit", *args, stdout=out)
        return out.getvalue()

    def test_it_says_how_many_learners_it_checked_when_the_books_balance(self, ledger, give, user, other_user):
        give(user, 10)
        give(other_user, 4)

        assert "2 learners checked, the books balance" in self.run()

    def test_it_prints_a_line_per_break_and_exits_non_zero(self, ledger, give, user, other_user):
        give(user, 10)
        give(other_user, 4)
        break_the_books(user)

        with pytest.raises(CommandError) as failed:
            self.run()

        assert "1 break" in str(failed.value)

    def test_the_lines_name_the_learner_and_the_sums(self, ledger, give, user):
        give(user, 10)
        break_the_books(user)
        out = StringIO()

        with pytest.raises(CommandError):
            call_command("credits_audit", stdout=out)

        assert str(user.pk) in out.getvalue() and "ledger 10" in out.getvalue() and "buckets 0" in out.getvalue()

    def test_it_can_check_one_learner_by_id_or_by_email(self, ledger, give, user, other_user):
        give(user, 10)
        give(other_user, 4)
        break_the_books(other_user)

        assert "1 learner checked" in self.run("--user", str(user.pk))
        assert "1 learner checked" in self.run("--user", user.email)
        with pytest.raises(CommandError):
            self.run("--user", other_user.email)

    def test_an_unknown_learner_is_an_error(self):
        with pytest.raises(CommandError, match="No learner"):
            self.run("--user", "nobody@example.com")
