"""Unit under test: `console.services.overview.OverviewReport` (the numbers of the console's first page),
`console.services.attention` (the rules behind "needs attention") and `console.services.health.ConsoleHealth`.

Why: this page is how a maintainer decides whether Socra is fine. A lesson counted in the wrong range, a failed call
counted as a retry, spend that leaves out a provider or a warning that never fires would each send them the wrong way.
The data is fixed (a frozen clock and exact rows), so every number below is derived by hand.

Use cases:
- lessons: started, finished (ready) and failed in the range, and how many started and finished in the range before
- daily activity: per day (as the chart), lessons started and model calls made and worked, for the sparklines
- spend: the range's total, the average per lesson that made calls, month to date, and the monthly budget setting
- calls: total, worked first time, worked after a retry, failed, and attempts on a fallback model
- daily spend: one point per day (14, or 30 for 30d) ending today, each split by provider, with empty days included
- funnel: of the lessons started in the range, how many answered the quick check, were built, got a study sheet, had a
  test submitted, failed while building, or are waiting for the learner
- slowest steps: the 95th percentile call time per step, the six slowest, from calls that worked
- attention: lessons that failed in the last 24 hours; a model failing more than 20% of at least 20 calls; calls that
  waited for a rate limit today; providers with models bound but no API key
- every attention rule stays quiet when there is nothing to report, and the list is ordered by severity
- health: the database, Redis and Celery results, how many workers answered, and an unreachable broker is a result
- the report is built in the same number of queries however much data there is
- the endpoint: staff get the report, an unknown range is a 400, the default range is 7d
"""

from datetime import timedelta
from decimal import Decimal

import pytest

from console.periods import Periods
from console.services.attention import (
    AttentionContext,
    FailedLessonsRule,
    FailingModelRule,
    MissingKeyRule,
    RateLimitWaitRule,
)
from console.services.health import ConsoleHealth
from console.services.overview import OverviewReport
from lessons.models import Lesson, Quiz, QuizAttempt, TestSubmission
from lessons.stages import Route, Stage
from llm_registry.models import ModelCall

pytestmark = pytest.mark.django_db

H = timedelta(hours=1)
D = timedelta(days=1)


UP = {"ok": True, "latency_ms": 1, "detail": "fine"}
HEALTHY = {"status": "ok", "database": UP, "redis": UP, "celery": UP, "workers": 1}


class FakeHealth:
    def report(self):
        return HEALTHY


@pytest.fixture
def lesson_at(user, now):
    def _make(*, created, stage=Stage.READY, updated=None, route="lesson", error="", topic="Binary search"):
        lesson = Lesson.objects.create(owner=user, topic=topic, stage=stage, route=route, error=error)
        Lesson.objects.filter(pk=lesson.pk).update(created_at=created, updated_at=updated or created)
        return lesson

    return _make


@pytest.fixture
def data(lesson_at, make_call, now):
    """Six lessons and six calls placed around the frozen `now` (Sunday 2026-03-15 12:00)."""
    lessons = {
        "built": lesson_at(created=now - 2 * H, updated=now - 1 * H),  # today, ready
        "failed": lesson_at(created=now - 3 * H, updated=now - 2 * H, stage=Stage.FAILED, error="boom"),  # today
        "mastery": lesson_at(created=now - 26 * H, updated=now - 25 * H, route=Route.MASTERY),  # yesterday
        "waiting": lesson_at(created=now - 3 * D, stage=Stage.AWAITING_DIAGNOSTIC, route=""),  # this week
        "earlier": lesson_at(created=now - 20 * D, updated=now - 20 * D),  # only in the 30 day range
        "before": lesson_at(created=now - 10 * D, updated=now - 10 * D),  # in the week before the 7d range
    }
    for name in ("built", "mastery"):  # the quick check was answered
        quiz = Quiz.objects.create(lesson=lessons[name], kind=Quiz.Kind.DIAGNOSTIC, questions=[])
        QuizAttempt.objects.create(quiz=quiz, answers={}, result={})
    TestSubmission.objects.create(lesson=lessons["built"])

    def call(lesson, **fields):
        return make_call(lesson_id=lesson.id if lesson else None, **fields)

    calls = [
        call(lessons["built"], ago=1 * H, cost="0.010000", latency_ms=1000, input_tokens=100, output_tokens=50),
        call(
            lessons["built"],
            ago=2 * H,
            cost="0.002000",
            latency_ms=2000,
            attempt=2,
            provider_key="groq",
            model_name="openai/gpt-oss-120b",
        ),  # fmt: skip
        call(lessons["failed"], ago=3 * H, status=ModelCall.Status.FATAL_ERROR, latency_ms=500),
        call(
            lessons["failed"],
            ago=30 * timedelta(minutes=1),
            cost="0.003000",
            latency_ms=9000,
            fallback_index=1,
            node_key="page.generate",
            provider_key="groq",
            model_name="openai/gpt-oss-120b",
        ),  # fmt: skip
        call(lessons["mastery"], ago=1 * D, cost="0.020000", latency_ms=3000),  # yesterday noon
        call(None, ago=24 * D, cost="0.500000", latency_ms=1000),  # 2026-02-19: in 30d, before this month
    ]
    return lessons, calls


@pytest.fixture
def report(now):
    return OverviewReport(health=FakeHealth()).build("7d", now)


def test_lessons_count_what_started_finished_and_failed_in_the_range_and_before_it(data, now):
    seven = OverviewReport(health=FakeHealth()).build("7d", now)["lessons"]
    today = OverviewReport(health=FakeHealth()).build("today", now)["lessons"]
    month = OverviewReport(health=FakeHealth()).build("30d", now)["lessons"]

    # 7d = Mar 9 to now: built, failed, mastery, waiting started; built and mastery finished; one failed.
    # The 7 days before it (Mar 2 to 9) hold `before`.
    assert seven == {"started": 4, "finished": 2, "failed": 1, "previous_started": 1, "previous_finished": 1}
    # today: built and failed; yesterday: mastery
    assert today == {"started": 2, "finished": 1, "failed": 1, "previous_started": 1, "previous_finished": 1}
    assert month["started"] == 6 and month["previous_started"] == 0 and month["previous_finished"] == 0


def test_spend_totals_the_range_averages_per_lesson_and_tracks_the_month(data, now, settings):
    settings.CONSOLE_MONTHLY_BUDGET_USD = "40"

    week = OverviewReport(health=FakeHealth()).build("7d", now)["spend"]
    month = OverviewReport(health=FakeHealth()).build("30d", now)["spend"]

    # 0.010 + 0.002 + 0.003 + 0.020 over the three lessons that made calls
    assert week == {"range_total": "0.035000", "per_lesson_avg": "0.011667", "month_to_date": "0.035000",
                    "monthly_budget": "40.000000"}  # fmt: skip
    assert month["range_total"] == "0.535000" and month["month_to_date"] == "0.035000"  # Feb 19's 0.50 is not March's


def test_spend_is_zero_and_not_missing_when_nothing_was_called(lesson_at, now):
    spend = OverviewReport(health=FakeHealth()).build("7d", now)["spend"]

    assert spend == {"range_total": "0.000000", "per_lesson_avg": "0.000000", "month_to_date": "0.000000",
                     "monthly_budget": "25.000000"}  # fmt: skip


def test_calls_split_into_worked_retried_failed_and_fallbacks(data, report):
    assert report["calls"] == {"total": 5, "ok": 3, "retried": 1, "failed": 1, "fallbacks": 1}


def test_daily_spend_has_one_point_per_day_split_by_provider(data, report, now):
    daily = report["daily_spend"]

    assert len(daily) == 14 and daily[-1]["date"] == "2026-03-15" and daily[0]["date"] == "2026-03-02"
    assert daily[-1]["by_provider"] == {"gemini": "0.010000", "groq": "0.005000"}
    assert daily[-2] == {"date": "2026-03-14", "by_provider": {"gemini": "0.020000"}}
    assert daily[0]["by_provider"] == {}  # days with no spend are still there


def test_daily_spend_covers_30_days_for_the_long_range(data, now):
    daily = OverviewReport(health=FakeHealth()).build("30d", now)["daily_spend"]

    assert len(daily) == 30
    assert next(day for day in daily if day["date"] == "2026-02-19")["by_provider"] == {"gemini": "0.500000"}


def test_daily_activity_counts_lessons_started_and_calls_made_and_worked_each_day(data, report):
    days = {day["date"]: day for day in report["daily_activity"]}

    assert len(report["daily_activity"]) == 14 and report["daily_activity"][-1]["date"] == "2026-03-15"
    assert days["2026-03-15"] == {"date": "2026-03-15", "lessons_started": 2, "calls_total": 4, "calls_worked": 3}
    assert days["2026-03-14"] == {"date": "2026-03-14", "lessons_started": 1, "calls_total": 1, "calls_worked": 1}
    assert days["2026-03-12"]["lessons_started"] == 1 and days["2026-03-12"]["calls_total"] == 0
    assert days["2026-03-05"]["lessons_started"] == 1  # the lesson from ten days ago
    assert days["2026-03-03"] == {"date": "2026-03-03", "lessons_started": 0, "calls_total": 0, "calls_worked": 0}


def test_daily_activity_covers_30_days_for_the_long_range(data, now):
    days = OverviewReport(health=FakeHealth()).build("30d", now)["daily_activity"]

    assert len(days) == 30
    assert next(d for d in days if d["date"] == "2026-02-19")["calls_total"] == 1  # the call from 24 days ago


def test_funnel_follows_the_lessons_started_in_the_range(data, report):
    assert report["funnel"] == {"started": 4, "quick_check_done": 2, "built": 1, "test_submitted": 1,
                                "study_sheets": 1, "failed_building": 1, "waiting": 1}  # fmt: skip


def test_slowest_steps_are_the_95th_percentile_of_calls_that_worked_slowest_first(data, report):
    # learner.assess worked in 1.0, 2.0 and 3.0 s: p95 is 2.9 s (interpolated); page.generate worked once in 9.0 s
    assert report["slowest_steps"] == [
        {"node": "page.generate", "p95_s": 9.0},
        {"node": "learner.assess", "p95_s": 2.9},
    ]


def test_only_the_six_slowest_steps_are_listed(make_call, now):
    for index in range(8):
        make_call(node_key=f"step.{index}", latency_ms=1000 * (index + 1))

    steps = OverviewReport(health=FakeHealth()).build("7d", now)["slowest_steps"]

    assert [step["node"] for step in steps] == [f"step.{i}" for i in range(7, 1, -1)]


def test_the_report_names_its_range_and_carries_the_health(data, report, now):
    assert report["range"] == "7d" and report["health"] == HEALTHY
    assert report["period"] == {"start": "2026-03-09T00:00:00Z", "end": "2026-03-15T12:00:00Z"}


# --- attention rules ---------------------------------------------------------------------------------------------


def context(now, range_key="7d"):
    return AttentionContext(Periods().of(range_key, now), now)


def test_failed_lessons_in_the_last_24_hours_are_reported_with_the_latest_reason(data, now):
    [item] = FailedLessonsRule().evaluate(context(now))

    assert (item.kind, item.severity) == ("lessons_failed", "error")
    assert item.title == "1 lesson failed in the last 24 hours" and "boom" in item.detail
    assert item.link == "/console/runs?status=failed"


def test_older_failures_and_working_lessons_raise_nothing(lesson_at, now):
    lesson_at(created=now - 3 * D, updated=now - 2 * D, stage=Stage.FAILED, error="old")  # more than a day ago
    lesson_at(created=now - 1 * H)

    assert FailedLessonsRule().evaluate(context(now)) == []


def test_several_failed_lessons_are_pluralised(lesson_at, now):
    for _ in range(3):
        lesson_at(created=now - 3 * H, updated=now - 2 * H, stage=Stage.FAILED, error="boom")

    assert FailedLessonsRule().evaluate(context(now))[0].title == "3 lessons failed in the last 24 hours"


def fill(make_call, total, failed, model="gemini-3.5-flash"):
    for index in range(total):
        status = ModelCall.Status.INVALID_OUTPUT if index < failed else ModelCall.Status.OK
        make_call(model_name=model, status=status)


def test_a_model_failing_more_than_a_fifth_of_twenty_calls_is_reported_with_its_usual_problem(make_call, now):
    fill(make_call, total=20, failed=6)  # 30%

    [item] = FailingModelRule().evaluate(context(now))

    assert (item.kind, item.severity) == ("model_failing", "warning")
    assert item.title == "gemini-3.5-flash is failing 30% of calls"
    assert "invalid output" in item.detail.lower()
    assert item.link == "/console/usage?model=gemini-3.5-flash"


def test_a_model_failing_most_calls_is_an_error(make_call, now):
    fill(make_call, total=20, failed=12)

    assert FailingModelRule().evaluate(context(now))[0].severity == "error"


@pytest.mark.parametrize(("total", "failed"), [(20, 4), (19, 19), (40, 8)])
def test_exactly_a_fifth_or_too_few_calls_do_not_count(make_call, now, total, failed):
    fill(make_call, total=total, failed=failed)

    assert FailingModelRule().evaluate(context(now)) == []


def test_calls_that_waited_for_a_rate_limit_today_are_reported(make_call, now):
    make_call(rate_limit_wait_ms=30_000, ago=1 * H)
    make_call(rate_limit_wait_ms=30_000, ago=2 * H)
    make_call(rate_limit_wait_ms=60_000, ago=1 * D)  # yesterday: not today's
    make_call(ago=1 * H)  # did not wait

    [item] = RateLimitWaitRule().evaluate(context(now))

    assert (item.kind, item.severity) == ("rate_limit_waits", "info")
    assert item.title == "2 calls waited for a rate limit today"
    assert "1 minute" in item.detail


def test_a_call_that_gave_up_waiting_counts_as_a_wait(make_call, now):
    make_call(status=ModelCall.Status.FATAL_ERROR, error="RateLimitWaitExceeded('Rate limit for provider:groq ...')")

    assert RateLimitWaitRule().evaluate(context(now))[0].title == "1 call waited for a rate limit today"


def test_no_waits_no_warning(make_call, now):
    make_call()

    assert RateLimitWaitRule().evaluate(context(now)) == []


def test_a_provider_with_bound_models_but_no_key_is_reported(registry, monkeypatch, now):
    registry.bind("learner.assess", "oss")
    registry.bind("lesson.plan", "oss")
    monkeypatch.delenv("GROQ_API_KEY")

    [item] = MissingKeyRule().evaluate(context(now))

    assert (item.kind, item.severity) == ("provider_key_missing", "error")
    assert item.title == "groq has no API key" and "GROQ_API_KEY" in item.detail and "2 steps" in item.detail
    assert item.link == "/console/models"


def test_a_provider_whose_key_is_set_is_fine(registry, now):
    registry.bind("learner.assess", "oss")
    registry.bind("lesson.plan", "flash")

    assert MissingKeyRule().evaluate(context(now)) == []


def test_only_the_provider_without_a_key_is_named(registry, monkeypatch, now):
    registry.bind("learner.assess", "oss")
    registry.bind("lesson.plan", "flash")
    monkeypatch.delenv("GEMINI_API_KEY")

    assert [item.title for item in MissingKeyRule().evaluate(context(now))] == ["gemini has no API key"]


def test_a_disabled_binding_does_not_make_a_missing_key_matter(registry, monkeypatch, now):
    registry.bind("lesson.plan", "flash", is_enabled=False)
    monkeypatch.delenv("GEMINI_API_KEY")

    assert MissingKeyRule().evaluate(context(now)) == []


def test_an_unbound_provider_without_a_key_is_not_a_problem_yet(registry, monkeypatch, now):
    monkeypatch.delenv("GROQ_API_KEY")

    assert MissingKeyRule().evaluate(context(now)) == []


def test_attention_is_ordered_by_severity_most_serious_first(data, registry, monkeypatch, make_call, now):
    registry.bind("learner.assess", "oss")
    monkeypatch.delenv("GROQ_API_KEY")  # error
    fill(make_call, total=20, failed=6)  # warning
    make_call(rate_limit_wait_ms=1000)  # info

    attention = OverviewReport(health=FakeHealth()).build("7d", now)["attention"]

    assert [item["severity"] for item in attention] == ["error", "error", "warning", "info"]
    assert {item["kind"] for item in attention} == {"lessons_failed", "provider_key_missing", "model_failing",
                                                    "rate_limit_waits"}  # fmt: skip


def test_all_quiet_means_nothing_needs_attention(now, registry):
    assert OverviewReport(health=FakeHealth()).build("7d", now)["attention"] == []


# --- health ---------------------------------------------------------------------------------------------------------


class FakeCheck:
    def __init__(self, name, ok=True, detail="fine"):
        self.name, self._ok, self._detail = name, ok, detail

    def run(self):
        from core.health import CheckResult

        return CheckResult(self._ok, 3, self._detail)


class FakeCelery:
    name = "celery"

    def __init__(self, workers):
        self.workers = workers

    def worker_count(self):
        return self.workers


class BrokenCelery:
    name = "celery"

    def worker_count(self):
        raise ConnectionError("broker refused")


def test_health_reports_each_dependency_and_the_worker_count():
    health = ConsoleHealth(checks=[FakeCheck("database"), FakeCheck("redis", detail="redis 7")], celery=FakeCelery(2))

    report = health.report()

    celery = report.pop("celery")
    assert report == {
        "status": "ok",
        "database": {"ok": True, "latency_ms": 3, "detail": "fine"},
        "redis": {"ok": True, "latency_ms": 3, "detail": "redis 7"},
        "workers": 2,
    }
    assert (celery["ok"], celery["detail"]) == (True, "2 worker(s)") and celery["latency_ms"] >= 0


def test_health_is_degraded_when_a_dependency_is_down_or_no_worker_answers():
    down = ConsoleHealth(checks=[FakeCheck("database"), FakeCheck("redis", ok=False, detail="refused")],
                         celery=FakeCelery(1))  # fmt: skip
    idle = ConsoleHealth(checks=[FakeCheck("database")], celery=FakeCelery(0))

    assert down.report()["status"] == "degraded" and down.report()["redis"]["ok"] is False
    assert idle.report()["status"] == "degraded" and idle.report()["workers"] == 0
    assert idle.report()["celery"]["detail"] == "no workers responded"


def test_health_reports_an_unreachable_broker_instead_of_raising():
    report = ConsoleHealth(checks=[FakeCheck("database")], celery=BrokenCelery()).report()

    assert report["status"] == "degraded" and report["workers"] == 0
    assert report["celery"]["ok"] is False and report["celery"]["detail"] == "broker refused"


# --- cost of building it, and the endpoint --------------------------------------------------------------------------


def test_the_report_is_built_in_the_same_number_of_queries_however_much_data_there_is(
    lesson_at, make_call, registry, now, count_queries
):
    def build():
        OverviewReport(health=FakeHealth()).build("30d", now)

    # both data sets reach every branch (a failed lesson makes one rule look further), so only the size differs
    for stage in (Stage.READY, Stage.READY, Stage.FAILED):
        lesson = lesson_at(created=now - 2 * H, updated=now - 1 * H, stage=stage, error="x")
        make_call(lesson_id=lesson.id, cost="0.01")
    few = count_queries(build)

    for index in range(15):
        lesson = lesson_at(created=now - 2 * H, updated=now - 1 * H, stage=Stage.FAILED, error="x")
        for model in ("a", "b", "c"):
            make_call(lesson_id=lesson.id, cost="0.01", model_name=model, node_key=f"n{index}")
    many = count_queries(build)

    assert many == few


@pytest.fixture
def fake_health(monkeypatch):
    from console.views.overview import OverviewView

    monkeypatch.setattr(OverviewView, "health", FakeHealth())


def test_staff_get_the_overview_for_the_default_range(staff_client, data, fake_health):
    body = staff_client.get("/api/console/overview").json()

    assert body["range"] == "7d" and body["calls"]["total"] == 5
    assert set(body) == {
        "range", "period", "health", "lessons", "spend", "calls", "daily_spend", "daily_activity", "funnel",
        "slowest_steps", "attention",
    }  # fmt: skip


def test_an_unknown_range_is_a_bad_request(staff_client, fake_health):
    response = staff_client.get("/api/console/overview?range=yesterday")

    assert response.status_code == 400 and "range" in response.json()["fields"]


def test_money_is_a_decimal_string(staff_client, data, fake_health):
    spend = staff_client.get("/api/console/overview?range=7d").json()["spend"]

    assert spend["range_total"] == "0.035000" and Decimal(spend["range_total"]) == Decimal("0.035")
