"""Unit under test: `credits.tick.HourlyTick` and the `credits.tick` Celery task that runs it every hour (credits
plan T14).

Why: correctness never waits for this job (a lapsed bucket is already unspendable), but the books should say so, a
reserve
nothing will settle should go back, and a break in the ledger should be noticed within the hour, not at the next
audit. The
job is run by a scheduler that may run it twice, late, or from two places, so every part of it must be harmless to
repeat.

Use cases:
- one tick writes off lapsed buckets, releases reserves whose run failed, and checks the ledger, and reports each
- a break in the ledger is logged as an error and reported, not raised, so the other jobs still ran
- a part that raises is reported and does not stop the others
- a second tick right after the first changes nothing
- the task is registered under the name `credits.tick`, runs a tick and returns a plain report
- the beat schedule runs it every hour
"""

import logging
from datetime import timedelta

import pytest

from config.celery import app as celery_app
from credits.models import CreditBucket, CreditHold, CreditTransaction
from credits.tick import HourlyTick

pytestmark = pytest.mark.django_db


@pytest.fixture
def tick(ledger):
    return HourlyTick(ledger=ledger)


def lapse_one_bucket(user, give, clock):
    give(user, 5, days=1)
    clock.advance(days=2)


class TestOneTick:
    def test_it_writes_off_lapsed_buckets(self, tick, user, give, clock):
        lapse_one_bucket(user, give, clock)

        report = tick.run()

        assert report.expired_buckets == 1 and report.expired_credits == 5
        assert CreditTransaction.objects.filter(user=user, type="expire").count() == 1

    def test_it_releases_a_reserve_whose_run_failed(self, tick, user, give, make_lesson, ledger):
        from credits.gate import CreditGate
        from credits.pricing.seed import PriceSeed
        from lessons.metering import ActionContext, AuthorizationLedger, CompletionPoints, MeteredAction
        from lessons.models import GraphRun

        PriceSeed().apply()
        give(user, 20)
        lesson = make_lesson()
        size = {"entry": "diagnostic", "intent": "lesson", "origin": "direct", "covers": "diagnostic"}
        action = MeteredAction.LESSON_CREATE
        context = ActionContext(
            user, action, size, lesson.id, f"lesson.create:{lesson.id}", False, CompletionPoints.of(action, size)
        )
        authorization = CreditGate(ledger=ledger).authorize(context)
        GraphRun.objects.create(
            lesson=lesson,
            graph=GraphRun.Graph.FLOW,
            trigger=GraphRun.Trigger.START,
            status=GraphRun.Status.FAILED,
            payload=AuthorizationLedger().payload(authorization),
        )

        report = tick.run()

        assert report.released_holds == 1
        assert CreditHold.objects.get(pk=authorization.id).status == "released" and ledger.balance(user) == 20

    def test_it_checks_the_ledger_and_reports_clean_books(self, tick, user, give):
        give(user, 5)

        report = tick.run()

        assert report.audit_breaks == 0

    def test_a_break_is_logged_as_an_error_and_reported_not_raised(self, tick, user, give, caplog):
        give(user, 5)
        CreditBucket.objects.filter(user=user).update(amount_remaining=1)

        with caplog.at_level(logging.ERROR, logger="credits.tick"):
            report = tick.run()

        assert report.audit_breaks == 1
        assert any(str(user.pk) in record.getMessage() for record in caplog.records if record.levelno == logging.ERROR)

    def test_a_part_that_raises_is_reported_and_the_others_still_run(self, user, give, clock, ledger):
        class Broken:
            def run(self):
                raise RuntimeError("down")

        lapse_one_bucket(user, give, clock)

        report = HourlyTick(ledger=ledger, reconciler=Broken()).run()

        assert report.failed == ["reconciler"] and report.expired_buckets == 1 and report.audit_breaks == 0


class TestHarmless:
    def test_a_second_tick_changes_nothing(self, tick, user, give, clock):
        lapse_one_bucket(user, give, clock)
        tick.run()
        rows, buckets = CreditTransaction.objects.count(), CreditBucket.objects.count()

        second = tick.run()

        assert (second.expired_buckets, second.released_holds, second.audit_breaks) == (0, 0, 0)
        assert CreditTransaction.objects.count() == rows and CreditBucket.objects.count() == buckets

    def test_a_tick_with_nothing_to_do_is_quiet(self, tick):
        report = tick.run()

        assert (report.expired_buckets, report.released_holds, report.audit_breaks, report.failed) == (0, 0, 0, [])

    def test_the_clock_decides_what_has_lapsed(self, tick, user, give, clock):
        give(user, 5, days=1)
        clock.advance(days=1, seconds=-1)
        assert tick.run().expired_buckets == 0

        clock.advance(seconds=1)

        assert tick.run().expired_buckets == 1 and clock.now() > clock.now() - timedelta(seconds=1)


class TestTheTask:
    def test_it_is_registered_by_name(self):
        import credits.tasks  # noqa: F401  (a worker finds it by autodiscovery)

        assert "credits.tick" in celery_app.tasks

    def test_running_it_returns_a_plain_report(self, user, give):
        from credits.tasks import tick

        give(user, 5)

        result = tick()

        assert result == {
            "expired_buckets": 0, "expired_credits": 0, "released_holds": 0, "audit_breaks": 0, "failed": [],
        }  # fmt: skip

    def test_the_schedule_runs_it_every_hour(self):
        from django.conf import settings

        entry = settings.CELERY_BEAT_SCHEDULE["credits.tick"]

        assert entry["task"] == "credits.tick" and entry["schedule"] == 3600
        assert celery_app.conf.beat_schedule["credits.tick"]["task"] == "credits.tick"
