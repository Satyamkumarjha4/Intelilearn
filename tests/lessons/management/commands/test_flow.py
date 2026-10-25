"""Unit under test: `manage.py flow` (start, answer, show, retry, runs), the terminal driver for the lesson flow.

Why: it is how the flow is exercised against the real registry without a browser or a worker, and how Phase 5's
"does Binary search come out right?" is checked. A command that picks the wrong learner, mis-scores a scripted quiz or
hides the reason a step was refused makes that check misleading.

Use cases:
- start creates a lesson for the only user, runs it inline to the first quiz, and prints the stage
- start needs --email when there is more than one user, and refuses an unknown one
- answer --correct N takes the quiz with the first N right, prints the score and route, and runs on to the assessment
- answer accepts explicit JSON answers and refuses invalid JSON or an impossible --correct
- answer refuses a lesson that is not waiting, with the service's reason
- a lesson can be named by a prefix of its id; an unknown or ambiguous prefix is an error
- show prints the report and --json prints the stored fields
- choose resumes a mastery lesson with the sheet, writes it, and show lists it; sheet asks for another one
- choose and sheet refuse a lesson in the wrong stage with the service's reason
- retry resumes a failed lesson from its checkpoint, and refuses one that did not fail
- runs lists the lesson's runs
"""

import json
from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from langgraph.checkpoint.memory import InMemorySaver

from graph.context import FlowContext
from lessons import tasks
from lessons.models import Lesson, Stage
from lessons.runner import FlowRunner

pytestmark = pytest.mark.django_db(transaction=True)

ASSESSMENT = {
    "level": "intermediate", "known_concepts": ["Searching a list"], "gaps": ["Halving the range"],
    "prerequisites_to_cover": [], "start_point": "Halving the range", "author_notes": "Brisk.", "confidence": "medium",
}  # fmt: skip


class Memory:
    def __init__(self):
        self.saver_ = InMemorySaver()

    def saver(self):
        from contextlib import nullcontext

        return nullcontext(self.saver_)


class Silent:
    def publish(self, run_id, event):
        pass


@pytest.fixture
def inline(monkeypatch, gateway, bound_registry):
    """Inline runs use a runner with a scripted gateway and an in-memory checkpointer."""
    checkpoints = Memory()

    def runner():
        return FlowRunner(
            checkpointers=checkpoints,
            events=Silent(),
            context_factory=lambda run_id: FlowContext(gateway=gateway, run_id=run_id),
        )

    monkeypatch.setattr(tasks, "RUNNER", runner)
    return gateway


def flow(*args) -> str:
    out = StringIO()
    call_command("flow", *args, stdout=out)
    return out.getvalue()


def start(inline, valid_bundle, user):
    inline.script("diagnostic.generate", valid_bundle)
    output = flow("start", "Binary search", "--inline", "--context", "for my exam")
    lesson = Lesson.objects.get(owner=user)
    return lesson, output


def test_start_creates_a_lesson_for_the_only_user_and_runs_it_to_the_first_quiz(inline, valid_bundle, user):
    lesson, output = start(inline, valid_bundle, user)

    assert f"lesson {lesson.id}" in output and "stage: awaiting_diagnostic" in output
    assert lesson.user_context == "for my exam"


def test_start_needs_an_email_when_there_is_more_than_one_user(inline, user, other_user):
    with pytest.raises(CommandError, match="--email"):
        flow("start", "Binary search", "--inline")


def test_start_refuses_an_unknown_email(inline, user):
    with pytest.raises(CommandError, match="nobody@example.com"):
        flow("start", "Binary search", "--email", "nobody@example.com", "--inline")


def test_start_picks_the_user_named_by_email(inline, valid_bundle, user, other_user):
    inline.script("diagnostic.generate", valid_bundle)

    flow("start", "Binary search", "--email", "GRACE@example.com", "--inline")

    assert Lesson.objects.get().owner == other_user


def test_start_with_no_users_says_so(inline, db):
    with pytest.raises(CommandError, match="no users"):
        flow("start", "Binary search", "--inline")


def test_answer_takes_the_quiz_and_runs_on_to_the_assessment(inline, valid_bundle, user):
    lesson, _ = start(inline, valid_bundle, user)
    inline.script("learner.assess", ASSESSMENT)

    output = flow("answer", str(lesson.id), "diagnostic", "--correct", "5", "--inline")

    assert "5/10 correct → route lesson" in output
    lesson.refresh_from_db()
    assert lesson.stage == Stage.GENERATING_LESSON and lesson.assessment["level"] == "intermediate"


def test_answer_accepts_explicit_answers_as_json(inline, valid_bundle, user):
    lesson, _ = start(inline, valid_bundle, user)
    answers = {q["id"]: "dont_know" for q in valid_bundle["diagnostic"]}
    inline.script("diagnostic.generate", valid_bundle)

    output = flow("answer", str(lesson.id), "diagnostic", "--answers", json.dumps(answers), "--inline")

    assert "0/10 correct → route prerequisite" in output


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--answers", "{nope"], "not valid JSON"),
        (["--correct", "11"], "between 0 and 10"),
        (["--correct", "-1"], "between 0"),
    ],
)
def test_answer_refuses_bad_input(inline, valid_bundle, user, args, message):
    lesson, _ = start(inline, valid_bundle, user)

    with pytest.raises(CommandError, match=message):
        flow("answer", str(lesson.id), "diagnostic", *args, "--inline")


def test_answer_says_when_the_quiz_does_not_exist_yet(inline, user, make_lesson):
    lesson = make_lesson()

    with pytest.raises(CommandError, match="no diagnostic quiz"):
        flow("answer", str(lesson.id), "diagnostic", "--correct", "5", "--inline")


def test_answer_surfaces_the_reason_a_lesson_is_not_waiting(inline, valid_bundle, user):
    lesson, _ = start(inline, valid_bundle, user)
    Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.GENERATING_LESSON)

    with pytest.raises(CommandError, match="not waiting for the diagnostic quiz"):
        flow("answer", str(lesson.id), "diagnostic", "--correct", "5", "--inline")


def test_a_lesson_can_be_named_by_a_prefix_of_its_id(inline, valid_bundle, user):
    lesson, _ = start(inline, valid_bundle, user)

    output = flow("show", str(lesson.id)[:8])

    assert str(lesson.id) in output


def test_an_unknown_prefix_is_an_error(inline, user):
    with pytest.raises(CommandError, match="No lesson matches"):
        flow("show", "ffffffff")


def test_an_ambiguous_prefix_is_an_error(inline, user, make_lesson):
    make_lesson(), make_lesson()

    with pytest.raises(CommandError, match="more than one"):
        flow("show", "")


def test_show_prints_the_report_and_json_prints_the_stored_fields(inline, valid_bundle, user):
    lesson, _ = start(inline, valid_bundle, user)

    report = flow("show", str(lesson.id))
    data = json.loads(flow("show", str(lesson.id), "--json"))

    assert "Binary search" in report and "stage: awaiting_diagnostic" in report
    assert data["topic"] == "Binary search" and data["stage"] == "awaiting_diagnostic"


def test_retry_resumes_a_failed_lesson_from_its_checkpoint(inline, valid_bundle, user):
    bad = {**valid_bundle, "diagnostic": valid_bundle["diagnostic"][:9]}
    inline.script("diagnostic.generate", bad, bad, valid_bundle)
    flow("start", "Binary search", "--inline")
    lesson = Lesson.objects.get()
    assert lesson.stage == Stage.FAILED

    output = flow("retry", str(lesson.id), "--inline")

    assert "stage: awaiting_diagnostic" in output
    assert len(inline.called("diagnostic.generate")) == 3


def test_retry_refuses_a_lesson_that_did_not_fail(inline, user, make_lesson):
    with pytest.raises(CommandError, match="Only a failed lesson"):
        flow("retry", str(make_lesson().id), "--inline")


def test_runs_lists_the_lessons_runs(inline, valid_bundle, user):
    lesson, _ = start(inline, valid_bundle, user)

    output = flow("runs", str(lesson.id))

    assert "flow/start  paused" in output


def test_choose_writes_the_sheet_and_sheet_asks_for_another(inline, valid_bundle, user):
    from support.study_data import CONCEPTS, make_cheat_sheet, make_revision_sheet

    bundle = {
        **valid_bundle,
        "diagnostic": [{**q, "concept": f"{CONCEPTS[n % 2]} {n}"} for n, q in enumerate(valid_bundle["diagnostic"])],
    }
    inline.script("diagnostic.generate", bundle).script("study.generate", make_cheat_sheet(), make_revision_sheet())
    flow("start", "Binary search", "--inline")
    lesson = Lesson.objects.get()
    flow("answer", str(lesson.id), "diagnostic", "--correct", "10", "--inline")

    chosen = flow("choose", str(lesson.id), "cheat_sheet", "--inline")
    more = flow("sheet", str(lesson.id), "revision_sheet", "--inline")

    assert "stage: ready" in chosen and "route: mastery" in chosen and "run " in more
    report = flow("show", str(lesson.id))
    assert "cheat_sheet: Binary search cheat sheet" in report and "revision_sheet: Binary search revision" in report


def test_choose_and_sheet_refuse_the_wrong_stage(inline, user, make_lesson):
    lesson = make_lesson()

    with pytest.raises(CommandError, match="not waiting for a study sheet"):
        flow("choose", str(lesson.id), "cheat_sheet", "--inline")
    with pytest.raises(CommandError, match="only available once a mastery lesson is ready"):
        flow("sheet", str(lesson.id), "cheat_sheet", "--inline")
