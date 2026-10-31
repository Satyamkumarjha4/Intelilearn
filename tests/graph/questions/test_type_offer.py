"""Unit under test: `graph.questions.traits.TopicTraits` and `QuestionTypes.for_topic` / `QuestionTypes.code_format`:
which kinds of question a quick quiz offers for a topic and a question count (plan D17, §9.5).

Why: a history quiz has no numerical questions and a five-question quiz has no room for essays. The wizard shows only
the kinds that make sense, and the server applies the very same rule, so a hand-made request cannot ask for what the
screen hides. When the model that judges the topic is off or fails, the rule must still offer something: every kind the
count allows.

Use cases:
- multiple choice and multiple select are always offered
- numerical questions are offered only for a quantitative topic
- short and long answers are offered only from 10 questions
- a topic nobody has judged (no traits) offers everything the count allows
- the kinds come back in a fixed order
- the code format is offered for a programming topic, and only with short or long answers
- the calibration quiz is multiple choice only, whatever the topic
- traits survive being stored as JSON; a stored value that is not traits is read as "unknown"
- a lesson's traits come from its plan and its pages, with no model: quantitative from the plan, programming when a page
  has code
"""

import pytest
from support.lesson_data import make_page, make_plan

from graph.questions import QuestionTypes
from graph.questions.traits import TopicTraits

MATHS = TopicTraits(quantitative=True, programming=False)
HISTORY = TopicTraits(quantitative=False, programming=False)
CODING = TopicTraits(quantitative=False, programming=True)


class TestWhichKindsAreOffered:
    def test_choice_questions_are_always_offered(self):
        assert QuestionTypes.for_topic(HISTORY, 5) == ("mcq", "msq")

    def test_numerical_questions_only_for_a_quantitative_topic(self):
        assert "numerical" in QuestionTypes.for_topic(MATHS, 5)
        assert "numerical" not in QuestionTypes.for_topic(HISTORY, 30)

    @pytest.mark.parametrize(("count", "offered"), [(5, False), (10, True), (15, True), (30, True)])
    def test_short_and_long_answers_only_from_ten_questions(self, count, offered):
        kinds = QuestionTypes.for_topic(HISTORY, count)

        assert ("short_answer" in kinds) is offered and ("long_answer" in kinds) is offered

    def test_the_kinds_come_in_a_fixed_order(self):
        assert QuestionTypes.for_topic(MATHS, 10) == ("mcq", "msq", "numerical", "short_answer", "long_answer")

    def test_a_topic_nobody_judged_offers_everything_the_count_allows(self):
        assert QuestionTypes.for_topic(None, 10) == ("mcq", "msq", "numerical", "short_answer", "long_answer")
        assert QuestionTypes.for_topic(None, 5) == ("mcq", "msq", "numerical")

    def test_the_fallback_traits_are_everything(self):
        assert QuestionTypes.for_topic(TopicTraits.everything(), 5) == QuestionTypes.for_topic(None, 5)

    @pytest.mark.parametrize("count", [0, -5, 7, 31, 2.5, "10", None, True])
    def test_a_count_that_is_not_a_preset_is_refused(self, count):
        with pytest.raises(ValueError, match="preset"):
            QuestionTypes.for_topic(MATHS, count)


class TestTheCodeFormat:
    def test_a_programming_topic_with_short_or_long_answers_offers_code(self):
        assert QuestionTypes.code_format(CODING, ("short_answer",))
        assert QuestionTypes.code_format(CODING, ("mcq", "long_answer"))

    def test_choice_questions_have_no_code_format(self):
        assert not QuestionTypes.code_format(CODING, ("mcq", "msq"))

    def test_a_topic_that_is_not_programming_has_none(self):
        assert not QuestionTypes.code_format(HISTORY, ("short_answer", "long_answer"))

    def test_an_unjudged_topic_has_none_because_code_is_never_assumed(self):
        assert not QuestionTypes.code_format(None, ("short_answer",))


class TestTheCalibrationQuiz:
    def test_it_is_multiple_choice_only(self):
        assert QuestionTypes.for_calibration() == ("mcq",)


class TestTraits:
    def test_traits_survive_json(self):
        assert TopicTraits.from_dict(MATHS.as_dict()) == MATHS

    @pytest.mark.parametrize("stored", [None, {}, {"quantitative": "yes"}, {"quantitative": True}, "maths", []])
    def test_a_stored_value_that_is_not_traits_is_unknown(self, stored):
        assert TopicTraits.from_dict(stored) is None

    def test_traits_from_a_lesson_come_from_its_plan_and_pages_with_no_model(self):
        plan = make_plan(quantitative=True)
        pages = {key: make_page(key, plan) for key in ("introduction", "core", "advanced")}
        pages["core"]["sections"][0]["code_snippets"] = [{"language": "python", "code": "x = 1", "explanation": "e"}]

        traits = TopicTraits.of_lessons([(plan, pages)])

        assert traits == TopicTraits(quantitative=True, programming=True)

    def test_several_lessons_are_quantitative_or_programming_if_any_of_them_is(self):
        history, maths = make_plan(quantitative=False), make_plan(quantitative=True)

        assert TopicTraits.of_lessons([(history, {}), (maths, {})]) == TopicTraits(True, False)
        assert TopicTraits.of_lessons([(history, {})]) == TopicTraits(False, False)

    def test_a_lesson_without_a_plan_adds_nothing(self):
        assert TopicTraits.of_lessons([(None, None)]) == TopicTraits(False, False)
