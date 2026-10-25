"""Unit under test: the `grade_test` nodes in `graph.nodes.grading`: loading a submission, sending only the answers that
need a judgement to the model, checking its marks, and saving the finished score card.

Why: this is the learner's test score. A blank answer sent to a model costs money and invites a made-up mark; marks the
model gets wrong must be sent back for another try, not saved; a run that cannot grade must say so instead of saving a
half-finished card as final; and the card must keep what was marked automatically.

Use cases:
- load_submission: finds the lesson's test and the answers, the learner's language, and the open-ended answers worth
  grading (not the automatic ones, not the blank ones)
- the router goes to the model only when there is something to grade
- grade_open: asks `test.grade` about those answers and keeps the report, counting the attempt
- validate_grade: accepts a complete grading; sends a bad one back with the problems, and gives up with the reason when
  attempts run out
- persist_grade: saves the card with the model's marks and the automatic ones, marks the submission graded, and with
  nothing to grade saves the automatic card alone
- fail_grade: ends the run with the reason
"""

import pytest
from support.fixtures import budget_snapshot
from support.lesson_data import make_final_test

from graph.errors import RunFailed
from graph.nodes.grading import (
    FailGradeNode,
    GradeOpenNode,
    LoadSubmissionNode,
    OpenItemsRouter,
    PersistGradeNode,
    ValidateGradeNode,
)
from graph.schemas import GradeReport
from lessons.models import Lesson, Stage, TestSubmission

FINAL_TEST = make_final_test()
BY_TYPE = {}
for question in FINAL_TEST["questions"]:
    BY_TYPE.setdefault(question["type"], []).append(question["id"])
MCQ, NUM, SHORT, LONG, CODE = (BY_TYPE[t][0] for t in ("mcq", "numerical", "short_answer", "long_answer", "code"))
ANSWERS = {MCQ: 1, NUM: "4", SHORT: "Halve the range each time.", LONG: "   ", CODE: "def search(items, t): return 0"}


@pytest.fixture
def submitted(lesson, lesson_state):
    Lesson.objects.filter(pk=lesson.pk).update(
        stage=Stage.READY, final_test=FINAL_TEST, config_snapshot=budget_snapshot(),
        settings_snapshot=lesson_state["settings"],
    )  # fmt: skip
    submission = TestSubmission.objects.create(lesson=lesson, answers=ANSWERS)
    return lesson_state | {"submission_id": str(submission.id)}, submission


def graded(*pairs):
    return {"grades": [{"question_id": qid, "awarded": awarded, "feedback": f"About {qid}."} for qid, awarded in pairs]}


class TestLoad:
    def test_it_loads_the_test_the_answers_and_what_needs_a_judgement(self, submitted, runtime):
        state, _ = submitted

        update = LoadSubmissionNode()(state, runtime)

        assert update["test_answers"] == ANSWERS and update["final_test"] == FINAL_TEST
        assert [item["id"] for item in update["grading_items"]] == [
            SHORT,
            CODE,
        ]  # not the mcq, not the blank long answer
        assert update["profile"] == {"preferred_language": "en"} and update["snapshot"] == budget_snapshot()

    def test_a_submission_of_another_lesson_is_not_found(self, submitted, runtime, make_lesson):
        state, _ = submitted
        other = make_lesson(topic="Other")

        with pytest.raises(TestSubmission.DoesNotExist):
            LoadSubmissionNode()(state | {"lesson_id": str(other.id)}, runtime)


class TestRouter:
    def test_it_asks_the_model_only_when_there_is_something_to_grade(self):
        assert OpenItemsRouter()({"grading_items": [{"id": "s1"}]}) == "grade_open"
        assert OpenItemsRouter()({"grading_items": []}) == "persist_grade"


class TestGradeOpen:
    def state(self, submitted, runtime):
        return submitted[0] | LoadSubmissionNode()(submitted[0], runtime)

    def test_it_asks_test_grade_about_the_open_answers_and_keeps_the_report(self, submitted, runtime, gateway):
        report = graded((SHORT, 1), (CODE, 2))
        gateway.script("test.grade", GradeReport(**report))
        state = self.state(submitted, runtime)

        update = GradeOpenNode()(state, runtime)

        assert update == {"grade_report": report, "attempts": {"grading": 1}}
        call = gateway.called("test.grade")[0]
        assert call.schema is GradeReport and "Halve the range each time." in call.messages[1].content
        assert (
            "Binary search" in call.messages[1].content
            and "   " not in call.messages[1].content.split("learner_answer")[-1][:5]
        )

    def test_a_rejected_attempt_is_fed_back(self, submitted, runtime, gateway):
        gateway.script("test.grade", GradeReport(**graded((SHORT, 1), (CODE, 2))))
        state = self.state(submitted, runtime) | {
            "feedback": {"grading": ["s1: awarded 9 but the question is worth 4."]}
        }

        GradeOpenNode()(state, runtime)

        assert "s1: awarded 9" in gateway.called("test.grade")[0].messages[1].content


class TestValidate:
    def state(self, submitted, runtime, report, **extra):
        loaded = submitted[0] | LoadSubmissionNode()(submitted[0], runtime)
        return loaded | {"grade_report": report} | extra

    def test_a_complete_grading_passes(self, submitted, runtime):
        update = ValidateGradeNode()(self.state(submitted, runtime, graded((SHORT, 2), (CODE, 0))), runtime)

        assert update == {"feedback": {"grading": []}}

    def test_a_bad_grading_is_sent_back_with_the_problems(self, submitted, runtime, events):
        state = self.state(submitted, runtime, graded((SHORT, 99)), attempts={"grading": 1})

        update = ValidateGradeNode()(state, runtime)

        assert update["feedback"]["grading"][0].startswith("Grade every question; these are missing")
        assert "error" not in update and events.of_type("attempt")[0]["node"] == "grade_open"

    def test_it_gives_up_with_the_reason_when_attempts_run_out(self, submitted, runtime):
        state = self.state(submitted, runtime, graded((SHORT, 99)), attempts={"grading": 2})

        update = ValidateGradeNode()(state, runtime)

        assert update["error"].startswith("The grading still failed its checks after 2 attempts: ")
        assert update["failed_node"] == "grade_open"


class TestPersist:
    def test_the_card_holds_the_models_marks_and_the_automatic_ones(self, submitted, runtime):
        state = submitted[0] | LoadSubmissionNode()(submitted[0], runtime)
        state |= {"grade_report": graded((SHORT, 1), (CODE, 2))}

        PersistGradeNode()(state, runtime)

        stored = TestSubmission.objects.get(pk=state["submission_id"])
        assert stored.status == TestSubmission.Status.GRADED and stored.graded_at is not None
        rows = {r["id"]: r for r in stored.result["questions"]}
        assert (rows[MCQ]["awarded"], rows[MCQ]["graded_by"]) == (2, "auto")
        assert (rows[SHORT]["awarded"], rows[SHORT]["graded_by"], rows[SHORT]["feedback"]) == (
            1,
            "model",
            f"About {SHORT}.",
        )
        assert (rows[LONG]["awarded"], rows[LONG]["feedback"]) == (0, "No answer given.")
        assert stored.result["complete"] is True and stored.result["score"]["available"] == 20

    def test_with_nothing_to_grade_the_automatic_card_is_saved_alone(self, submitted, runtime, lesson):
        TestSubmission.objects.filter(pk=submitted[0]["submission_id"]).update(answers={MCQ: 1, NUM: "4"})
        state = submitted[0] | LoadSubmissionNode()(submitted[0], runtime)

        PersistGradeNode()(state, runtime)

        stored = TestSubmission.objects.get(pk=state["submission_id"])
        assert stored.status == TestSubmission.Status.GRADED and state["grading_items"] == []
        assert stored.result["score"]["awarded"] == 2 + 2  # mcq and numerical, 2 marks each


def test_a_run_that_cannot_grade_ends_with_the_reason(runtime):
    with pytest.raises(RunFailed, match="The grading still failed"):
        FailGradeNode()({"error": "The grading still failed its checks"}, runtime)
    with pytest.raises(RunFailed, match="could not be graded"):
        FailGradeNode()({}, runtime)
