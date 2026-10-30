"""Unit under test: `graph.nodes.questions`: `PlanBatchesNode`, `GenerateQuestionsNode`, `QuestionSends` and
`QuestionRound`, the pipeline that writes the questions of a test, shared by the author stage and the retake graph.

Why: a lesson test is a fixed blueprint, so "done" means every one of its ten cells has a good question of the right
type and difficulty, none of them a repeat. The join has to retry what failed, ask again for what is still missing, and
give up with a reason when it cannot fill the cells, and it must do this the same way wherever it runs. Batch results
arrive in parallel and in any order.

Use cases:
- plan_batches: all ten cells in two batches in round 1; later rounds plan only the cells with no question; every round
  has new batch ids and forgets what was known about the batches it plans
- generate_questions: asks test.generate for the batch's cells, gives each question its cell's id, sets the marks and
  the numerical answer in code, and keeps the questions even when they have problems, with the problems as feedback
- the sends carry the batch and the feedback it earned; a subset can be sent again
- the join decides nothing while a batch has not reported (pending)
- the join retries a batch that has problems and attempts left, naming the reason
- the join accepts a batch that has problems once its attempts are used up, when its questions still fit their cells,
  and warns
- a question of the wrong type or difficulty for its cell, one that cannot be used (a numerical question with no
  answer), and one that repeats a question already asked fill nothing, and those cells are planned again
- with rounds left the unfilled cells are planned again; with none left the join stops short with the reason and resets
  the state so a retry starts from the beginning
- when every cell is filled the round is complete, and closing it again gives the same answer
"""

import copy

import pytest
from support.fixtures import budget_snapshot
from support.lesson_data import make_blueprint_test, make_state
from support.question_data import written

from graph.nodes.questions import GenerateQuestionsNode, PlanBatchesNode, QuestionRound, QuestionSends
from graph.questions import BatchPlanner, LessonTestBlueprint
from graph.schemas import QuestionBatch

pytestmark = pytest.mark.django_db

BLUEPRINT = LessonTestBlueprint.for_topic(True)
QUESTIONS = make_blueprint_test()["questions"]


def planned(round_no=1, cells=BLUEPRINT.cells):
    batches = BatchPlanner(size=5).plan(cells, round_no)
    return {"round": round_no, "batches": [{"id": b.id, "cells": [c.as_dict() for c in b.cells]} for b in batches]}


def after_writing(**extra):
    """A state in which both batches of round 1 have reported with the stored test's questions."""
    state = make_state() | {"question_plan": planned(), "settings": {"question_batch_size": 5}}
    state["question_batches"] = {
        "b1-1": {"questions": copy.deepcopy(QUESTIONS[:5])},
        "b1-2": {"questions": copy.deepcopy(QUESTIONS[5:])},
    }
    state["feedback"], state["attempts"] = {}, {"batch:b1-1": 1, "batch:b1-2": 1}
    state["snapshot"] = {"nodes": {"test.generate": {"chain": ["m"], "max_attempts": 2}}}
    return state | extra


class TestPlanBatches:
    def test_round_one_plans_all_ten_cells_in_two_batches(self, lesson_state, runtime):
        state = make_state() | {"settings": {"question_batch_size": 5}}

        update = PlanBatchesNode()(state, runtime)

        batches = update["question_plan"]["batches"]
        assert update["question_round"] == 1 and update["question_plan"]["round"] == 1
        assert [b["id"] for b in batches] == ["b1-1", "b1-2"] and [len(b["cells"]) for b in batches] == [5, 5]
        assert [c["index"] for b in batches for c in b["cells"]] == list(range(10))

    def test_it_forgets_the_attempts_and_the_problems_of_the_batches_it_plans(self, runtime):
        update = PlanBatchesNode()(make_state() | {"settings": {}}, runtime)

        assert update["attempts"] == {"batch:b1-1": None, "batch:b1-2": None}
        assert update["feedback"] == {"batch:b1-1": None, "batch:b1-2": None}

    def test_a_later_round_plans_only_the_cells_without_a_question(self, runtime):
        accepted = {str(n): QUESTIONS[n] for n in range(7)}
        state = make_state() | {"settings": {}, "accepted": accepted, "question_round": 1}

        update = PlanBatchesNode()(state, runtime)

        (batch,) = update["question_plan"]["batches"]
        assert update["question_round"] == 2 and batch["id"] == "b2-1"
        assert [c["index"] for c in batch["cells"]] == [7, 8, 9]

    def test_with_every_cell_filled_there_is_nothing_to_plan(self, runtime):
        accepted = {str(n): QUESTIONS[n] for n in range(10)}

        update = PlanBatchesNode()(make_state() | {"settings": {}, "accepted": accepted}, runtime)

        assert update["question_plan"]["batches"] == []

    def test_the_batch_size_comes_from_the_settings(self, runtime):
        update = PlanBatchesNode()(make_state() | {"settings": {"question_batch_size": 10}}, runtime)

        assert [len(b["cells"]) for b in update["question_plan"]["batches"]] == [10]


class TestGenerateQuestions:
    def branch(self, **extra):
        plan = planned()
        base = {
            "key": "b1-1",
            "item": plan["batches"][0],
            "feedback": [],
            "exclusions": [],
            "snapshot": budget_snapshot(),
        }
        return make_state() | base | extra

    def model_output(self, cells):
        return QuestionBatch(questions=[written(c["type"], 90 + n, c["difficulty"]) for n, c in enumerate(cells)])

    def test_it_asks_for_the_cells_of_the_batch_and_gives_each_question_its_cells_id(self, gateway, runtime):
        branch = self.branch()
        gateway.script("test.generate", self.model_output(branch["item"]["cells"]))

        update = GenerateQuestionsNode()(branch, runtime)

        questions = update["question_batches"]["b1-1"]["questions"]
        assert [q["id"] for q in questions] == ["t1", "t2", "t3", "t4", "t5"]
        assert [(q["type"], q["difficulty"]) for q in questions] == [
            (c["type"], c["difficulty"]) for c in branch["item"]["cells"]
        ]
        assert update["feedback"] == {"batch:b1-1": []} and update["attempts"] == {"batch:b1-1": 1}
        call = gateway.called("test.generate")[0]
        assert call.schema is QuestionBatch and "exactly 5 questions" in call.messages[0].content

    def test_marks_and_the_numerical_answer_are_set_by_code(self, gateway, runtime):
        branch = self.branch(key="b1-2", item=planned()["batches"][1])
        gateway.script("test.generate", self.model_output(branch["item"]["cells"]))

        questions = GenerateQuestionsNode()(branch, runtime)["question_batches"]["b1-2"]["questions"]

        assert [q["marks"] for q in questions] == [c["marks"] for c in branch["item"]["cells"]]
        numerical = next(q for q in questions if q["type"] == "numerical")
        assert numerical["answer"] == 4

    def test_questions_with_problems_are_kept_and_the_problems_are_the_feedback(self, gateway, runtime):
        branch = self.branch()
        output = self.model_output(branch["item"]["cells"])
        output.questions[0].difficulty = "expert"
        gateway.script("test.generate", output)

        update = GenerateQuestionsNode()(branch, runtime)

        assert len(update["question_batches"]["b1-1"]["questions"]) == 5
        assert any("must be easy; it is expert" in p for p in update["feedback"]["batch:b1-1"])

    def test_the_feedback_of_the_last_attempt_is_in_the_prompt(self, gateway, runtime):
        branch = self.branch(feedback=["Question t1 must be easy; it is expert."])
        gateway.script("test.generate", self.model_output(branch["item"]["cells"]))

        GenerateQuestionsNode()(branch, runtime)

        assert "Question t1 must be easy; it is expert." in gateway.called("test.generate")[0].messages[1].content

    def test_the_questions_already_asked_are_in_the_prompt(self, gateway, runtime):
        branch = self.branch(exclusions=["What is a stale question?"])
        gateway.script("test.generate", self.model_output(branch["item"]["cells"]))

        GenerateQuestionsNode()(branch, runtime)

        assert "What is a stale question?" in gateway.called("test.generate")[0].messages[1].content


class TestSends:
    def test_one_send_per_batch_with_the_batch_and_the_feedback_it_earned(self):
        state = make_state() | {"question_plan": planned(), "feedback": {"batch:b1-2": ["fix t6"]}}

        sends = QuestionSends.of(state)

        assert [s.node for s in sends] == ["generate_questions", "generate_questions"]
        assert [s.arg["item"]["id"] for s in sends] == ["b1-1", "b1-2"]
        assert [s.arg["feedback"] for s in sends] == [[], ["fix t6"]]
        assert sends[0].arg["blueprint"] == make_state()["blueprint"] and sends[0].arg["topic"] == "Binary search"

    def test_only_the_named_batches_can_be_sent_again(self):
        sends = QuestionSends.of(make_state() | {"question_plan": planned()}, {"b1-2"})

        assert [s.arg["item"]["id"] for s in sends] == ["b1-2"]


class TestRound:
    def close(self, state, ctx):
        return QuestionRound().close(state, ctx)

    def test_nothing_is_decided_while_a_batch_has_not_reported(self, ctx):
        state = after_writing()
        del state["question_batches"]["b1-2"]

        result = self.close(state, ctx)

        assert result.outcome == "pending" and result.update == {"question_outcome": "pending"}

    def test_good_questions_for_every_cell_complete_the_round(self, ctx):
        result = self.close(after_writing(), ctx)

        assert result.outcome == "complete" and result.update["question_outcome"] == "complete"
        assert sorted(result.update["accepted"], key=int) == [str(n) for n in range(10)]
        assert result.update["accepted"]["3"]["id"] == "t4" and result.update["warnings"] == []

    def test_closing_a_complete_round_again_gives_the_same_answer(self, ctx):
        first = self.close(after_writing(), ctx)

        again = self.close(after_writing(accepted=first.update["accepted"]), ctx)

        assert again.outcome == "complete" and again.update["accepted"] == first.update["accepted"]

    def test_a_batch_with_problems_and_attempts_left_is_retried_with_the_reason(self, ctx, events):
        state = after_writing(feedback={"batch:b1-2": ["Question t7 is wrong."]})

        result = self.close(state, ctx)

        assert result.outcome == "retry" and result.retry == ("b1-2",)
        assert events.of_type("attempt") == [
            {"type": "attempt", "node": "generate_questions:b1-2", "reason": "Question t7 is wrong."}
        ]

    def test_a_batch_that_used_its_attempts_is_accepted_with_a_warning_when_its_questions_fit(self, ctx, events):
        state = after_writing(
            feedback={"batch:b1-2": ["Question t7 is wrong."]}, attempts={"batch:b1-1": 1, "batch:b1-2": 2}
        )

        result = self.close(state, ctx)

        assert result.outcome == "complete"
        assert result.update["warnings"] == ["Some questions were kept despite: Question t7 is wrong."]
        assert events.of_type("warning")

    def test_a_question_of_the_wrong_type_for_its_cell_fills_nothing(self, ctx):
        state = after_writing()
        state["question_batches"]["b1-1"]["questions"][0] = QUESTIONS[3]  # an msq where cell 0 wants an mcq

        result = self.close(state, ctx)

        assert (
            result.outcome == "replan" and "0" not in result.update["accepted"] and len(result.update["accepted"]) == 9
        )

    def test_a_numerical_question_with_no_answer_cannot_be_used(self, ctx):
        state = after_writing()
        numerical = next(q for q in state["question_batches"]["b1-2"]["questions"] if q["type"] == "numerical")
        del numerical["answer"]

        result = self.close(state, ctx)

        assert result.outcome == "replan" and len(result.update["accepted"]) == 9

    def test_a_question_that_repeats_one_already_asked_fills_nothing(self, ctx):
        state = after_writing(exclusions=[QUESTIONS[2]["question"]])

        result = self.close(state, ctx)

        assert result.outcome == "replan" and "2" not in result.update["accepted"]

    def test_a_question_that_repeats_an_earlier_one_in_the_set_fills_nothing(self, ctx):
        state = after_writing()
        state["question_batches"]["b1-2"]["questions"][1]["question"] = QUESTIONS[0]["question"]

        result = self.close(state, ctx)

        assert result.outcome == "replan" and "6" not in result.update["accepted"] and "0" in result.update["accepted"]

    def test_with_no_rounds_left_the_test_cannot_be_filled_and_the_state_starts_over(self, ctx):
        state = after_writing(question_plan=planned(round_no=2))
        state["question_batches"] = {
            "b2-1": {"questions": copy.deepcopy(QUESTIONS[:5])},
            "b2-2": {"questions": copy.deepcopy(QUESTIONS[5:])},
        }
        state["question_batches"]["b2-1"]["questions"][4] = QUESTIONS[0]  # a type clash for cell 4's difficulty

        result = self.close(state | {"attempts": {}}, ctx)

        assert result.outcome == "short"
        assert "no usable question for cell(s) 5 after 2 rounds" in result.update["error"]
        assert (result.update["failed_node"], result.update["question_round"], result.update["accepted"]) == (
            "plan_batches", 0, {},
        )  # fmt: skip
        assert result.update["retry_keys"] == []

    @pytest.mark.parametrize("rounds_left", [True, False])
    def test_a_round_that_fills_nothing_is_a_replan_or_short_by_the_budget(self, ctx, rounds_left):
        state = after_writing(question_plan=planned(round_no=1 if rounds_left else 2))
        state["question_batches"] = {
            batch["id"]: {"questions": [QUESTIONS[3]] * len(batch["cells"])}
            for batch in state["question_plan"]["batches"]
        }

        assert self.close(state | {"attempts": {}}, ctx).outcome == ("replan" if rounds_left else "short")
