"""Unit under test: `console.services.runs` (`RunQuery`, `RunTimeline`, `NodePhases`, `RunActions`) and the endpoints
`GET /api/console/runs`, `GET /api/console/runs/{id}`, `POST /api/console/runs/{id}/retry` and `.../cancel`.

Why: when a learner's lesson breaks, this is where the cause is found and the fix is started. A timeline that puts a
step at the wrong time, a retry that skips the rules the learner's own Retry button follows, or a cancel that leaves a
lesson half-stopped would each waste the one chance to see what went wrong.

Use cases:
- the list shows each run with its lesson, learner, state, duration, calls and cost; the newest first, in pages
- the list filters by status (one or several), by graph, and by a search of the topic, learner name or email
- an unknown status or graph is a 400; a run that has not started has no duration, a running one has its age so far
- the list runs the same number of queries for three runs and for thirty
- one run shows its error, its timeline and its last 20 model calls (newest first); an unknown or malformed id is a 404
- the timeline orders steps by when they started and says when each started and how long it took
- a step is `ran`, `retried` (the graph ran it again), `failed` (failed or degraded) or `waiting` (it is where a paused
  run waits for the learner, so it has no duration); a step still running has its time so far
- a run from before timings were kept still lists its steps, without times
- steps are grouped into the phases of the lesson (diagnose, author, build, post, other) by the code module of the node
- Retry is the learner's retry: a failed lesson gets a new run, as staff; other lessons, other graphs and busy lessons
  are 409s; Cancel stops an active run and fails the lesson so it can be retried, once
- both write an audit entry; neither is open to a learner
"""

from datetime import UTC, datetime, timedelta

import pytest

from console.models import AuditEntry
from console.services.runs import NodePhases, RunTimeline
from lessons.models import GraphRun, Lesson
from lessons.stages import Stage

pytestmark = pytest.mark.django_db

START = datetime(2026, 3, 15, 10, 0, 0, tzinfo=UTC)
STARTED = START.isoformat()


def at(seconds):
    return (START + timedelta(seconds=seconds)).isoformat()


def timing(start, end=None, retries=0):
    return {"started_at": at(start), "finished_at": None if end is None else at(end), "retries": retries}


@pytest.fixture
def make_run(lesson, now):
    def _make(lesson_=None, *, created=START - timedelta(seconds=5), **fields):
        defaults = dict(graph=GraphRun.Graph.FLOW, trigger=GraphRun.Trigger.START, status=GraphRun.Status.SUCCEEDED)
        run = GraphRun.objects.create(lesson=lesson_ or lesson, **{**defaults, **fields})
        GraphRun.objects.filter(pk=run.pk).update(created_at=created)
        run.refresh_from_db()
        return run

    return _make


@pytest.fixture
def finished_run(make_run, make_call):
    run = make_run(started_at=START, finished_at=START + timedelta(seconds=125))
    for index in range(3):
        make_call(run_id=run.id, cost="0.010000", ago=timedelta(hours=1, minutes=index))
    return run


# --- the list ----------------------------------------------------------------------------------------------------


def test_a_row_of_the_list_describes_the_run_its_lesson_and_what_it_cost(staff_client, finished_run, lesson, user):
    [row] = staff_client.get("/api/console/runs").json()["results"]

    assert row == {
        "id": str(finished_run.id),
        "lesson_id": str(lesson.id),
        "topic": "Binary search",
        "learner_name": "Ada Lovelace",
        "graph": "flow",
        "trigger": "start",
        "status": "succeeded",
        "stage": "preparing_diagnostic",
        "duration_s": 125.0,
        "calls": 3,
        "cost": "0.030000",
        "created_at": "2026-03-15T09:59:55Z",
    }


def test_a_run_that_has_not_started_has_no_duration_and_a_running_one_has_its_age(staff_client, make_run, now):
    make_run(status=GraphRun.Status.QUEUED)
    make_run(status=GraphRun.Status.RUNNING, started_at=now - timedelta(minutes=30), created=now - timedelta(hours=1))

    durations = {r["status"]: r["duration_s"] for r in staff_client.get("/api/console/runs").json()["results"]}

    assert durations == {"queued": None, "running": 1800.0}


def test_a_run_without_calls_has_zero_calls_and_cost(staff_client, make_run):
    make_run()

    [row] = staff_client.get("/api/console/runs").json()["results"]

    assert (row["calls"], row["cost"]) == (0, "0.000000")


def test_runs_come_newest_first_in_pages(staff_client, make_run, now):
    runs = [make_run(created=now - timedelta(hours=hours)) for hours in (5, 4, 3, 2, 1)]

    first = staff_client.get("/api/console/runs?page_size=2").json()
    second = staff_client.get(first["next"]).json()

    assert [r["id"] for r in first["results"]] == [str(runs[4].id), str(runs[3].id)]
    assert [r["id"] for r in second["results"]] == [str(runs[2].id), str(runs[1].id)]
    assert first["previous"] is None and second["next"]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("status=failed", {"failed"}),
        ("status=failed,running", {"failed", "running"}),
        ("graph=grade_test", {"grade"}),
        ("graph=flow&status=succeeded", {"ok"}),
        ("q=quantum", {"failed"}),
        ("q=GRACE", {"failed", "grade"}),
        ("q=grace@example", {"failed", "grade"}),
        ("q=Other", {"grade"}),
        ("q=nothing-matches", set()),
        ("", {"ok", "failed", "running", "grade"}),
    ],
)
def test_the_list_filters(staff_client, make_run, make_lesson, other_user, query, expected):
    other_lesson = make_lesson(owner=other_user, topic="Quantum tunnelling")
    runs = {
        "ok": make_run(status="succeeded"),
        "failed": make_run(other_lesson, status="failed"),
        "running": make_run(status="running"),
        "grade": make_run(
            make_lesson(owner=other_user, topic="Other"), graph="grade_test", trigger="grade", status="succeeded"
        ),  # fmt: skip
    }
    wanted = {str(runs[name].id) for name in expected}

    ids = {r["id"] for r in staff_client.get(f"/api/console/runs?{query}").json()["results"]}

    assert ids == wanted


def test_an_unknown_status_or_graph_is_a_bad_request(staff_client):
    assert "status" in staff_client.get("/api/console/runs?status=exploded").json()["fields"]
    assert "graph" in staff_client.get("/api/console/runs?graph=nope").json()["fields"]


def test_the_list_query_count_does_not_grow_with_the_runs(
    staff_client, make_run, make_call, make_lesson, count_queries
):
    def fetch():
        assert staff_client.get("/api/console/runs?page_size=100").status_code == 200

    for _ in range(3):
        make_call(run_id=make_run(make_lesson()).id)
    few = count_queries(fetch)
    for _ in range(30):
        make_call(run_id=make_run(make_lesson()).id)
    many = count_queries(fetch)

    assert many == few


# --- one run ------------------------------------------------------------------------------------------------------


def test_a_run_shows_its_error_and_its_summary(staff_client, make_run, make_call):
    run = make_run(status="failed", error="Every AI model for the step 'page.generate' failed.", started_at=START,
                   finished_at=START + timedelta(seconds=40))  # fmt: skip
    make_call(run_id=run.id, cost="0.002000")

    body = staff_client.get(f"/api/console/runs/{run.id}").json()

    assert body["error"].startswith("Every AI model") and body["status"] == "failed"
    assert (body["topic"], body["calls"], body["cost"], body["duration_s"]) == ("Binary search", 1, "0.002000", 40.0)
    assert body["started_at"] == "2026-03-15T10:00:00Z" and body["finished_at"] == "2026-03-15T10:00:40Z"


def test_the_last_twenty_model_calls_come_newest_first(staff_client, make_run, make_call, now):
    run = make_run(started_at=START)
    for minute in range(25):
        make_call(run_id=run.id, ago=timedelta(minutes=minute + 1), latency_ms=1000 + minute)
    make_call(run_id=None)  # another run's, or none

    calls = staff_client.get(f"/api/console/runs/{run.id}").json()["model_calls"]

    assert len(calls) == 20 and calls[0]["latency_s"] == 1.0 and calls[-1]["latency_s"] == 1.019
    assert [c["created_at"] for c in calls] == sorted((c["created_at"] for c in calls), reverse=True)


def test_a_model_call_row_says_which_attempt_on_which_model_and_what_came_of_it(staff_client, make_run, make_call):
    run = make_run(started_at=START)
    make_call(run_id=run.id, node_key="page.generate", status="invalid_output", error="bad json", attempt=2,
              fallback_index=1, input_tokens=10, output_tokens=5, tool_calls=2, cost="0.001000",
              provider_key="groq", model_name="openai/gpt-oss-120b", latency_ms=1500)  # fmt: skip

    [call] = staff_client.get(f"/api/console/runs/{run.id}").json()["model_calls"]

    assert {k: v for k, v in call.items() if k not in ("id", "created_at")} == {
        "node": "page.generate", "provider": "groq", "model": "openai/gpt-oss-120b", "attempt": 2,
        "fallback_index": 1, "status": "invalid_output", "outcome": "failed", "latency_s": 1.5, "tokens_in": 10,
        "tokens_out": 5, "tool_calls": 2, "cost": "0.001000", "error": "bad json",
    }  # fmt: skip


def test_the_run_says_what_staff_can_do_with_it(staff_client, make_run, make_lesson):
    failed = make_run(make_lesson(stage=Stage.FAILED), status="failed")
    running = make_run(status="running")
    done = make_run(status="succeeded")

    def actions(run):
        body = staff_client.get(f"/api/console/runs/{run.id}").json()
        return body["can_retry"], body["can_cancel"]

    assert (actions(failed), actions(running), actions(done)) == ((True, False), (False, True), (False, False))


@pytest.mark.parametrize("run_id", ["not-a-uuid", "00000000-0000-0000-0000-000000000000"])
def test_an_unknown_or_malformed_run_is_a_404(staff_client, run_id):
    assert staff_client.get(f"/api/console/runs/{run_id}").status_code == 404


def test_the_detail_shows_runs_of_any_learner(staff_client, make_run, make_lesson, other_user):
    run = make_run(make_lesson(owner=other_user, topic="Not Ada's"))

    assert staff_client.get(f"/api/console/runs/{run.id}").json()["learner_name"] == "Grace Hopper"


def test_the_run_endpoint_adds_a_constant_number_of_queries_for_calls_and_steps(
    staff_client, make_run, make_call, count_queries
):
    run = make_run(started_at=START, node_timings={"load_context": timing(0, 1)}, node_status={"load_context": "done"})

    def fetch():
        assert staff_client.get(f"/api/console/runs/{run.id}").status_code == 200

    few = count_queries(fetch)
    for _ in range(30):
        make_call(run_id=run.id)
    GraphRun.objects.filter(pk=run.pk).update(
        node_timings={f"n{i}": timing(i, i + 1) for i in range(40)}, node_status={f"n{i}": "done" for i in range(40)}
    )

    assert count_queries(fetch) == few


# --- the timeline -------------------------------------------------------------------------------------------------


def build(run, now=START + timedelta(hours=2)):
    return RunTimeline(now=lambda: now).of(run)


def entry(timeline, node):
    return next(e for e in timeline if e["node"] == node)


def test_steps_are_ordered_by_start_with_their_offset_and_duration(make_run):
    run = make_run(
        started_at=START, status="succeeded",
        node_status={"plan_lesson": "done", "load_context": "done"},
        node_timings={"plan_lesson": timing(10, 40), "load_context": timing(0.5, 2.5)},
    )  # fmt: skip

    timeline = build(run)

    assert timeline == [
        {"node": "load_context", "phase": "diagnose", "start_offset_s": 0.5, "duration_s": 2.0, "state": "ran"},
        {"node": "plan_lesson", "phase": "author", "start_offset_s": 10.0, "duration_s": 30.0, "state": "ran"},
    ]


def test_a_step_the_graph_ran_again_is_retried(make_run):
    run = make_run(started_at=START, node_status={"generate_diagnostic": "done"},
                   node_timings={"generate_diagnostic": timing(2, 30, retries=2)})  # fmt: skip

    assert entry(build(run), "generate_diagnostic")["state"] == "retried"


@pytest.mark.parametrize("status", ["failed", "degraded"])
def test_a_step_that_failed_or_was_skipped_after_failing_is_failed(make_run, status):
    run = make_run(started_at=START, node_status={"render_check": status}, node_timings={"render_check": timing(5, 9)})

    assert entry(build(run), "render_check")["state"] == "failed"


def test_failed_wins_over_retried(make_run):
    run = make_run(started_at=START, node_status={"render_check": "failed"},
                   node_timings={"render_check": timing(5, 9, retries=3)})  # fmt: skip

    assert entry(build(run), "render_check")["state"] == "failed"


def test_the_step_a_paused_run_waits_in_is_waiting_and_has_no_duration(make_run):
    run = make_run(started_at=START, status="paused", node_status={"await_diagnostic": "running"},
                   node_timings={"await_diagnostic": timing(40)})  # fmt: skip

    assert entry(build(run), "await_diagnostic") == {
        "node": "await_diagnostic", "phase": "diagnose", "start_offset_s": 40.0, "duration_s": None,
        "state": "waiting",
    }  # fmt: skip


def test_a_step_still_running_in_an_active_run_has_its_time_so_far(make_run):
    run = make_run(started_at=START, status="running", node_status={"page_writer": "running"},
                   node_timings={"page_writer": timing(60)})  # fmt: skip

    step = entry(build(run, now=START + timedelta(seconds=100)), "page_writer")

    assert (step["state"], step["duration_s"]) == ("ran", 40.0)


def test_a_step_that_started_before_the_run_is_clamped_to_zero(make_run):
    run = make_run(started_at=START, node_status={"load_context": "done"}, node_timings={"load_context": timing(-3, 2)})

    assert entry(build(run), "load_context")["start_offset_s"] == 0.0


def test_a_run_that_never_started_measures_from_when_it_was_created(make_run):
    run = make_run(started_at=None, created=START, node_status={"load_context": "done"},
                   node_timings={"load_context": timing(4, 6)})  # fmt: skip

    assert entry(build(run), "load_context")["start_offset_s"] == 4.0


def test_a_run_from_before_timings_were_kept_lists_its_steps_without_times(make_run):
    run = make_run(started_at=START, node_status={"load_context": "done", "render_check": "failed"}, node_timings={})

    assert build(run) == [
        {"node": "load_context", "phase": "diagnose", "start_offset_s": None, "duration_s": None, "state": "ran"},
        {"node": "render_check", "phase": "build", "start_offset_s": None, "duration_s": None, "state": "failed"},
    ]


def test_a_run_with_no_steps_has_an_empty_timeline(make_run):
    assert build(make_run(status="queued")) == []


def test_steps_that_never_started_come_after_the_ones_that_did(make_run):
    run = make_run(started_at=START, node_status={"b_step": "done", "a_step": "done", "c_step": "done"},
                   node_timings={"a_step": timing(5, 6)})  # fmt: skip

    assert [e["node"] for e in build(run)] == ["a_step", "b_step", "c_step"]


@pytest.mark.parametrize(
    ("node", "phase"),
    [
        ("load_context", "diagnose"), ("generate_diagnostic", "diagnose"), ("assess_learner", "diagnose"),
        ("generate_study_material", "diagnose"), ("plan_lesson", "author"), ("compile_page", "build"),
        ("render_check", "build"), ("repair_runtime", "post"), ("grade_open", "post"), ("mark_failed", "other"),
        ("a_node_that_does_not_exist", "other"),
    ],
)  # fmt: skip
def test_a_step_belongs_to_the_phase_of_the_module_that_defines_it(node, phase):
    assert NodePhases().of(node) == phase


# --- retry and cancel ---------------------------------------------------------------------------------------------


def test_retry_starts_a_new_run_for_a_failed_lesson_as_staff(staff_client, staff_user, make_run, make_lesson, queue):
    lesson = make_lesson(stage=Stage.FAILED, error="boom")
    failed = make_run(lesson, status="failed")

    response = staff_client.post(f"/api/console/runs/{failed.id}/retry")

    assert response.status_code == 202
    new = GraphRun.objects.get(pk=response.json()["run_id"])
    assert (new.lesson_id, new.trigger, new.status) == (lesson.id, GraphRun.Trigger.RETRY, GraphRun.Status.QUEUED)
    assert response.json()["lesson_id"] == str(lesson.id) and queue.runs == [new]
    [entry] = AuditEntry.objects.all()
    assert (entry.actor_id, entry.action, entry.target_type, entry.target_id) == (staff_user.id, "run.retry", "run",
                                                                                   str(failed.id))  # fmt: skip
    assert entry.after["new_run_id"] == str(new.id)


def test_retry_follows_the_learners_rules(staff_client, make_run, make_lesson, queue):
    ready = make_run(make_lesson(stage=Stage.READY), status="failed")
    busy_lesson = make_lesson(stage=Stage.FAILED)
    busy = make_run(busy_lesson, status="failed")
    make_run(busy_lesson, status="running")
    grading = make_run(make_lesson(stage=Stage.FAILED), graph="grade_test", trigger="grade", status="failed")

    assert staff_client.post(f"/api/console/runs/{ready.id}/retry").json()["code"] == "wrong_stage"
    assert staff_client.post(f"/api/console/runs/{busy.id}/retry").json()["code"] == "run_in_progress"
    assert staff_client.post(f"/api/console/runs/{grading.id}/retry").json()["code"] == "not_retryable"
    assert queue.runs == [] and not AuditEntry.objects.exists()  # a refused retry changes nothing and logs nothing


def test_retry_of_an_unknown_run_is_a_404(staff_client):
    assert staff_client.post("/api/console/runs/00000000-0000-0000-0000-000000000000/retry").status_code == 404


def test_cancel_stops_an_active_run_and_fails_the_lesson_so_it_can_be_retried(
    staff_client, staff_user, make_run, lesson, now
):
    run = make_run(status="running", started_at=START)

    response = staff_client.post(f"/api/console/runs/{run.id}/cancel")

    assert response.status_code == 202 and response.json()["status"] == "cancelled"
    run.refresh_from_db()
    lesson.refresh_from_db()
    assert run.status == GraphRun.Status.CANCELLED and run.finished_at == now
    assert lesson.stage == Stage.FAILED and "Cancelled" in lesson.error
    [entry] = AuditEntry.objects.all()
    assert (entry.action, entry.target_id, entry.before["status"], entry.after["status"]) == (
        "run.cancel", str(run.id), "running", "cancelled")  # fmt: skip


def test_cancelling_a_run_that_already_ended_is_a_conflict(staff_client, make_run):
    run = make_run(status="succeeded")

    response = staff_client.post(f"/api/console/runs/{run.id}/cancel")

    assert (response.status_code, response.json()["code"]) == (409, "run_ended")
    assert not AuditEntry.objects.exists()


def test_a_learner_can_neither_see_nor_act_on_runs_here(learner_client, make_run):
    run = make_run()

    assert learner_client.get("/api/console/runs").status_code == 404
    assert learner_client.get(f"/api/console/runs/{run.id}").status_code == 404
    assert learner_client.post(f"/api/console/runs/{run.id}/cancel").status_code == 404
    assert learner_client.post(f"/api/console/runs/{run.id}/retry").status_code == 404


def test_the_lesson_still_belongs_to_its_learner_after_a_staff_retry(staff_client, make_run, make_lesson, user, queue):
    lesson = make_lesson(stage=Stage.FAILED)
    staff_client.post(f"/api/console/runs/{make_run(lesson, status='failed').id}/retry")

    assert Lesson.objects.get(pk=lesson.pk).owner_id == user.id
