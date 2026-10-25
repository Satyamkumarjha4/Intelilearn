"""Unit under test: `graph.grading.ScoreCard` and `Solution`, which turn the automatic marks and the model's grades of a
submitted lesson test into the result the learner sees.

Why: this is the number a learner takes away. A blank answer marked by a model costs money and invites a made-up mark;
a model that awards more than a question is worth inflates the score; a card that claims to be complete while answers
are still being graded shows a false total; and the topics to revisit are the whole point of the test.

Use cases:
- questions with one right answer are marked automatically, with feedback that says what was expected when wrong
- a blank answer (missing, empty or only spaces) earns 0 with "No answer given." and is never sent for grading
- open-ended answers are listed for the model with their answer, and only when there is something to grade
- the model's marks and feedback are used for open-ended answers, capped at the question's marks
- while the model's grades are pending the card is not complete, their marks are not counted, and no topic is blamed
- the score adds up marks, with the percentage of all the marks the test is worth
- topics to revisit are the concepts of questions that lost marks, biggest loss first, each once
- each question carries its solution (the fields a learner may see after answering)
"""

import pytest

from graph.grading import AnswerGrader, ScoreCard, Solution


def mcq(qid="m1", concept="Halving", marks=2):
    return {
        "id": qid,
        "type": "mcq",
        "concept": concept,
        "marks": marks,
        "options": ["a", "b", "c", "d"],
        "correct_index": 1,
    }


def numerical(qid="n1", concept="Cost", marks=3):
    return {
        "id": qid,
        "type": "numerical",
        "concept": concept,
        "marks": marks,
        "answer": 4.0,
        "tolerance": 0.5,
        "unit": "steps",
    }


def short(qid="s1", concept="Invariant", marks=4):
    return {
        "id": qid,
        "type": "short_answer",
        "concept": concept,
        "marks": marks,
        "model_answer": "m",
        "key_points": ["k"],
    }


def code(qid="c1", concept="Loops", marks=5):
    return {"id": qid, "type": "code", "concept": concept, "marks": marks, "language": "python",
            "reference_solution": "pass", "test_cases": [{"input": "1", "expected_output": "1"}]}  # fmt: skip


QUESTIONS = [mcq(), numerical(), short(), code()]


def card(answers, model=None, questions=QUESTIONS):
    sheet = AnswerGrader().grade_all(questions, answers)
    return ScoreCard().build(questions, answers, sheet, model)


def row(result, qid):
    return next(r for r in result["questions"] if r["id"] == qid)


class TestAutomatic:
    def test_right_answers_are_marked_with_nothing_to_explain(self):
        result = card({"m1": 1, "n1": "4 steps"}, model={})

        assert (row(result, "m1")["awarded"], row(result, "m1")["feedback"], row(result, "m1")["graded_by"]) == (
            2,
            "Correct.",
            "auto",
        )
        assert (row(result, "n1")["awarded"], row(result, "n1")["correct"]) == (3, True)

    def test_a_wrong_choice_says_what_the_answer_was(self):
        result = card({"m1": 0}, model={})

        assert row(result, "m1")["feedback"] == 'The correct answer is "b".'
        assert (row(result, "m1")["awarded"], row(result, "m1")["correct"]) == (0, False)

    def test_a_wrong_number_says_what_was_expected_and_how_close_counts(self):
        result = card({"n1": "9"}, model={})

        assert row(result, "n1")["feedback"] == "The expected answer is 4 steps (accepted within ±0.5)."


class TestBlank:
    @pytest.mark.parametrize("blank", [None, "", "   \n"])
    def test_a_blank_answer_is_zero_without_asking_a_model(self, blank):
        answers = {"m1": blank, "n1": blank, "s1": blank, "c1": blank}

        result = card(answers, model={})

        assert [r["awarded"] for r in result["questions"]] == [0, 0, 0, 0]
        assert {r["feedback"] for r in result["questions"]} == {ScoreCard.NO_ANSWER}
        assert ScoreCard().open_items(QUESTIONS, answers) == []

    def test_a_missing_answer_is_blank_too(self):
        assert row(card({}, model={}), "s1")["feedback"] == ScoreCard.NO_ANSWER


class TestOpenItems:
    def test_open_ended_answers_go_to_the_model_with_the_learners_answer(self):
        items = ScoreCard().open_items(QUESTIONS, {"m1": 1, "s1": "halve it", "c1": "def f(): pass"})

        assert [(i["id"], i["answer"]) for i in items] == [("s1", "halve it"), ("c1", "def f(): pass")]
        assert items[0]["key_points"] == ["k"]

    def test_a_test_of_only_automatic_questions_has_nothing_to_grade(self):
        assert ScoreCard().open_items([mcq(), numerical()], {"m1": 1, "n1": "4"}) == []


class TestModelGrades:
    ANSWERS = {"m1": 1, "n1": "4", "s1": "halve it", "c1": "def f(): pass"}

    def test_the_models_marks_and_feedback_are_used(self):
        model = {
            "s1": {"awarded": 3, "feedback": "Good, but name the invariant."},
            "c1": {"awarded": 5, "feedback": "Works."},
        }

        result = card(self.ANSWERS, model)

        assert (row(result, "s1")["awarded"], row(result, "s1")["graded_by"]) == (3, "model")
        assert (row(result, "s1")["correct"], row(result, "c1")["correct"]) == (False, True)
        assert row(result, "s1")["feedback"] == "Good, but name the invariant."
        assert result["complete"] is True

    def test_marks_above_the_questions_worth_are_capped(self):
        result = card(self.ANSWERS, {"s1": {"awarded": 99, "feedback": "x"}, "c1": {"awarded": 0, "feedback": "y"}})

        assert row(result, "s1")["awarded"] == 4

    def test_while_grades_are_pending_the_card_is_not_complete_and_does_not_count_them(self):
        result = card(self.ANSWERS, None)

        assert result["complete"] is False
        assert (row(result, "s1")["awarded"], row(result, "s1")["graded_by"]) == (None, "none")
        assert result["score"] == {"awarded": 5, "available": 14, "percent": 36}
        assert result["topics_to_revisit"] == []

    def test_a_grade_the_model_left_out_stays_pending(self):
        result = card(self.ANSWERS, {"s1": {"awarded": 4, "feedback": "ok"}})

        assert row(result, "c1")["awarded"] is None and result["complete"] is False


class TestScoreAndTopics:
    def test_the_score_is_marks_over_all_the_marks_the_test_is_worth(self):
        result = card({"m1": 1, "n1": "4", "s1": "x", "c1": "y"},
                      {"s1": {"awarded": 2, "feedback": "a"}, "c1": {"awarded": 5, "feedback": "b"}})  # fmt: skip

        assert result["score"] == {"awarded": 12, "available": 14, "percent": 86}

    def test_topics_are_the_concepts_that_lost_marks_biggest_loss_first_each_once(self):
        questions = [
            mcq("m1", "Halving", 2),
            mcq("m2", "Halving", 2),
            short("s1", "Invariant", 4),
            numerical("n1", "Cost", 3),
        ]
        answers = {"m1": 0, "m2": 0, "s1": "x", "n1": "4"}

        result = card(answers, {"s1": {"awarded": 3, "feedback": "f"}}, questions)

        assert result["topics_to_revisit"] == ["Halving", "Invariant"]  # Halving lost 4, Invariant lost 1, Cost none

    def test_a_perfect_test_has_no_topics(self):
        result = card({"m1": 1, "n1": "4", "s1": "x", "c1": "y"},
                      {"s1": {"awarded": 4, "feedback": "a"}, "c1": {"awarded": 5, "feedback": "b"}})  # fmt: skip

        assert result["topics_to_revisit"] == [] and result["score"]["percent"] == 100

    def test_an_empty_test_scores_zero_of_zero(self):
        assert card({}, {}, [])["score"] == {"awarded": 0, "available": 0, "percent": 0}


class TestSolution:
    def test_it_keeps_only_the_answer_fields_that_are_set(self):
        assert Solution.of(mcq()) == {"correct_index": 1}
        assert Solution.of(numerical()) == {"answer": 4.0, "tolerance": 0.5, "unit": "steps"}

    def test_every_row_carries_its_solution(self):
        result = card({"m1": 1}, {})

        assert row(result, "m1")["solution"] == {"correct_index": 1}
        assert row(result, "s1")["solution"] == {"model_answer": "m", "key_points": ["k"]}
