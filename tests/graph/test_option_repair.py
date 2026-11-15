"""Unit under test: `graph.option_repair.OptionRepair`, which rewrites only the diagnostic questions whose options
repeat (or use "all of the above"), instead of the whole quiz going back to the model.

Why: a diagnostic quiz is 10 questions and a prerequisite quiz 5 more. A real model sometimes repeats an option in one
of them, and the validator then sent all fifteen back, three times, until the lesson failed ("Question q4: options
must all be different"). One bad question should cost one small call, not the whole quiz (and the lesson). The repair
is bounded: one try per question, a few questions at most, and when it cannot help the quiz is regenerated exactly as
before.

Use cases:
- a bundle whose options are all different is left alone, with no model call
- a question with a repeated option is rewritten by one call that names that question and the problem, and no other
  question is sent or changed; the rewrite keeps the question's place, id, band and concept
- a prerequisite question is repaired the same way and keeps its id and the prerequisite it belongs to
- "all of the above" style options are repaired like repeated ones
- a rewrite that still repeats an option is not used: the original stays and is reported, with no second try
- when no model answers, the question stays as it was and nothing is raised
- more than three offending questions mean the quiz as a whole is poor: nothing is repaired and no call is made
- the repair asks the diagnostic node's own models (`diagnostic.generate`), with the single-question schema
"""

import pytest

from graph.option_repair import OptionRepair
from graph.schemas import DiagnosticQuestion, PrerequisiteQuestion
from llm_registry.gateway import AllModelsFailed

pytestmark = pytest.mark.django_db


def repeat_an_option(question: dict) -> dict:
    question["options"][1] = question["options"][0]
    return question


def rewrite_of(question: dict, **changes) -> dict:
    """What a model would answer: the same question with four different options (and whatever `changes` say)."""
    return question | {"options": ["first", "second", "third", "fourth"]} | changes


@pytest.fixture
def state(lesson_state, valid_bundle):
    return lesson_state | {"bundle": valid_bundle}


class TestNothingToRepair:
    def test_a_good_bundle_is_left_alone_and_the_model_is_not_asked(self, state, ctx, gateway):
        result = OptionRepair().repair(state, ctx)

        assert result.bundle == state["bundle"] and result.repaired == [] and result.unrepaired == []
        assert gateway.calls == []


class TestARepeatedOption:
    def test_one_call_rewrites_only_that_question_and_keeps_its_place_and_identity(
        self, state, ctx, gateway, valid_bundle
    ):
        bad = repeat_an_option(valid_bundle["diagnostic"][3])
        gateway.script("diagnostic.generate", rewrite_of(bad, id="zzz", band="hard", concept="something else"))

        result = OptionRepair().repair(state, ctx)

        rewritten = result.bundle["diagnostic"][3]
        assert rewritten["options"] == ["first", "second", "third", "fourth"]
        assert (rewritten["id"], rewritten["band"], rewritten["concept"]) == (bad["id"], bad["band"], bad["concept"])
        assert result.repaired == [bad["id"]] and result.unrepaired == []
        untouched = [q for i, q in enumerate(result.bundle["diagnostic"]) if i != 3]
        assert untouched == [q for i, q in enumerate(valid_bundle["diagnostic"]) if i != 3]
        assert result.bundle["prerequisite_questions"] == valid_bundle["prerequisite_questions"]

    def test_the_call_names_the_question_and_the_problem_and_sends_no_other_question(
        self, state, ctx, gateway, valid_bundle
    ):
        bad = repeat_an_option(valid_bundle["diagnostic"][3])
        gateway.script("diagnostic.generate", rewrite_of(bad))

        OptionRepair().repair(state, ctx)

        (call,) = gateway.called("diagnostic.generate")
        sent = " ".join(str(m.content) for m in call.messages)
        assert call.schema is DiagnosticQuestion
        assert bad["question"] in sent and "options must all be different" in sent and state["topic"] in sent
        assert all(q["question"] not in sent for q in valid_bundle["diagnostic"] if q["id"] != bad["id"])

    def test_a_prerequisite_question_is_repaired_and_keeps_its_prerequisite(self, state, ctx, gateway, valid_bundle):
        bad = repeat_an_option(valid_bundle["prerequisite_questions"][2])
        gateway.script("diagnostic.generate", rewrite_of(bad, id="p9", prerequisite="Another"))

        result = OptionRepair().repair(state, ctx)

        fixed = result.bundle["prerequisite_questions"][2]
        assert fixed["options"] == ["first", "second", "third", "fourth"]
        assert (fixed["id"], fixed["prerequisite"]) == (bad["id"], bad["prerequisite"])
        assert gateway.called("diagnostic.generate")[0].schema is PrerequisiteQuestion
        assert result.repaired == [bad["id"]]

    def test_an_all_of_the_above_option_is_repaired_like_a_repeated_one(self, state, ctx, gateway, valid_bundle):
        bad = valid_bundle["diagnostic"][0]
        bad["options"][3] = "All of the above"
        gateway.script("diagnostic.generate", rewrite_of(bad))

        result = OptionRepair().repair(state, ctx)

        assert result.repaired == [bad["id"]] and "all of the above" not in str(result.bundle["diagnostic"][0]).lower()


class TestWhenTheRepairCannotHelp:
    def test_a_rewrite_that_still_repeats_an_option_is_not_used_and_is_not_tried_again(
        self, state, ctx, gateway, valid_bundle
    ):
        bad = repeat_an_option(valid_bundle["diagnostic"][3])
        gateway.script("diagnostic.generate", repeat_an_option(rewrite_of(bad)), rewrite_of(bad))

        result = OptionRepair().repair(state, ctx)

        assert result.bundle["diagnostic"][3] == bad
        assert result.repaired == [] and result.unrepaired == [bad["id"]]
        assert len(gateway.called("diagnostic.generate")) == 1

    def test_when_no_model_answers_the_question_stays_and_nothing_is_raised(self, state, ctx, gateway, valid_bundle):
        bad = repeat_an_option(valid_bundle["diagnostic"][3])
        gateway.script("diagnostic.generate", AllModelsFailed("diagnostic.generate", []))

        result = OptionRepair().repair(state, ctx)

        assert result.bundle["diagnostic"][3] == bad and result.unrepaired == [bad["id"]]

    def test_more_than_three_offending_questions_means_the_quiz_is_regenerated_instead(
        self, state, ctx, gateway, valid_bundle
    ):
        for index in range(4):
            repeat_an_option(valid_bundle["diagnostic"][index])

        result = OptionRepair().repair(state, ctx)

        assert result.bundle == state["bundle"] and result.repaired == []
        assert len(result.unrepaired) == 4 and gateway.calls == []

    def test_three_offending_questions_are_still_repaired_one_call_each(self, state, ctx, gateway, valid_bundle):
        bad = [repeat_an_option(valid_bundle["diagnostic"][index]) for index in (0, 4, 8)]
        for question in bad:
            gateway.script("diagnostic.generate", rewrite_of(question))

        result = OptionRepair().repair(state, ctx)

        assert result.repaired == [q["id"] for q in bad] and len(gateway.called("diagnostic.generate")) == 3
