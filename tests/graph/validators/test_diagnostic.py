"""Unit under test: `graph.validators.diagnostic.DiagnosticValidator`, `AssessmentGuard`, `DiagnosticReviewValidator`
and `graph.validators.base.CompositeValidator`: the deterministic rules a generated diagnostic bundle must satisfy.

Why: a diagnostic with the wrong band mix, repeated concepts, or a question that gives away another's answer produces a
misleading score, and the routing and the whole lesson are built on that score. Each problem is also the feedback the
model gets on its retry, so the wording must name what to change.

Use cases:
- a well-formed bundle has no problems
- the number of questions and the questions per band must match the settings
- question ids must be unique, across both quizzes
- every question must probe a different concept (compared ignoring case and punctuation)
- options must differ, and "all/none of the above" is refused
- one question must not reveal another's answer (short and numeric answers are exempt)
- there must be the configured number of prerequisites, each with exactly one question that uses its exact name
- LaTeX that does not parse is reported, and the checker is only asked when there is maths
- the assessment guard replaces the LLM's prerequisites with the deterministic ones
- a composite validator reports the first part that finds problems and stops there
- the LLM review validator turns reviewer issues into per-question problems
"""

import copy

import pytest
from support.quiz_data import make_prerequisites

from graph.validators import (
    AssessmentGuard,
    CompositeValidator,
    DiagnosticReviewValidator,
    DiagnosticValidator,
)


class FakeLatex:
    def __init__(self, bad: tuple[str, ...] = ()):
        self.bad, self.calls = bad, []

    def latex(self, expressions):
        self.calls.append(list(expressions))
        return [f"LaTeX does not parse: {e!r}" for e in expressions if e in self.bad]


def problems_for(bundle, settings, latex=None):
    return DiagnosticValidator(latex).validate(bundle, settings=settings)


def mutated(bundle, change):
    changed = copy.deepcopy(bundle)
    change(changed)
    return changed


def test_accepts_a_well_formed_bundle(valid_bundle, flow_settings):
    assert problems_for(valid_bundle, flow_settings) == []


class TestCountsAndBands:
    def test_rejects_the_wrong_number_of_questions(self, valid_bundle, flow_settings):
        bundle = mutated(valid_bundle, lambda b: b["diagnostic"].pop())

        problems = problems_for(bundle, flow_settings)

        assert any("exactly 10 questions" in p and "has 9" in p for p in problems)

    def test_rejects_an_unbalanced_band_mix(self, valid_bundle, flow_settings):
        bundle = mutated(valid_bundle, lambda b: b["diagnostic"][-1].update(band="basic"))

        problems = problems_for(bundle, flow_settings)

        assert any('Band "basic" must have exactly 2' in p for p in problems)
        assert any('Band "hard" must have exactly 2' in p for p in problems)

    def test_questions_per_band_comes_from_the_settings(self, valid_bundle, flow_settings):
        bundle = mutated(valid_bundle, lambda b: b.update(diagnostic=b["diagnostic"][::2]))

        assert problems_for(bundle, flow_settings | {"diagnostic_questions_per_band": 1}) == []


class TestIdentity:
    def test_rejects_repeated_question_ids(self, valid_bundle, flow_settings):
        bundle = mutated(valid_bundle, lambda b: b["diagnostic"][1].update(id="q1"))

        assert any("Question ids must be unique" in p and "q1" in p for p in problems_for(bundle, flow_settings))

    def test_rejects_ids_shared_between_the_two_quizzes(self, valid_bundle, flow_settings):
        bundle = mutated(valid_bundle, lambda b: b["prerequisite_questions"][0].update(id="q1"))

        assert any("across both quizzes" in p for p in problems_for(bundle, flow_settings))

    def test_rejects_repeated_concepts_ignoring_case_and_punctuation(self, valid_bundle, flow_settings):
        bundle = mutated(valid_bundle, lambda b: b["diagnostic"][3].update(concept="Concept BASIC 0!"))

        assert any("different concept" in p for p in problems_for(bundle, flow_settings))


class TestOptions:
    def test_rejects_duplicate_options(self, valid_bundle, flow_settings):
        bundle = mutated(
            valid_bundle, lambda b: b["diagnostic"][0]["options"].__setitem__(1, "concept basic 0 OPTION a")
        )

        assert any("Question q1: options must all be different" in p for p in problems_for(bundle, flow_settings))

    @pytest.mark.parametrize("option", ["All of the above", "none of these", "Both of them", "All the above"])
    def test_rejects_catch_all_options(self, valid_bundle, flow_settings, option):
        bundle = mutated(valid_bundle, lambda b: b["diagnostic"][2]["options"].__setitem__(3, option))

        assert any("all/none of the above" in p for p in problems_for(bundle, flow_settings))

    def test_rejects_catch_all_options_in_prerequisite_questions(self, valid_bundle, flow_settings):
        bundle = mutated(
            valid_bundle, lambda b: b["prerequisite_questions"][0]["options"].__setitem__(0, "None of the above")
        )

        assert any("Prerequisite question p1" in p for p in problems_for(bundle, flow_settings))


class TestIndependence:
    def test_rejects_a_question_that_reveals_another_answer(self, valid_bundle, flow_settings):
        bundle = mutated(
            valid_bundle,
            lambda b: b["diagnostic"][5].update(question="Given that concept basic 0 option A holds, what follows?"),
        )

        problems = problems_for(bundle, flow_settings)

        assert any("Question q6 reveals the answer to q1" in p for p in problems)

    def test_ignores_short_and_numeric_answers_that_appear_by_coincidence(self, valid_bundle, flow_settings):
        def change(b):
            b["diagnostic"][0]["options"] = ["3", "4", "5", "6"]
            b["diagnostic"][1]["options"] = ["O(n)", "O(1)", "O(n^2)", "O(log n)"]
            b["diagnostic"][4]["question"] = "A loop runs 3 times; its cost is O(n) overall. Which holds?"

        assert problems_for(mutated(valid_bundle, change), flow_settings) == []


class TestPrerequisites:
    def test_rejects_the_wrong_number_of_prerequisites(self, valid_bundle, flow_settings):
        def change(b):
            b["prerequisites"].pop()
            b["prerequisite_questions"].pop()

        problems = problems_for(mutated(valid_bundle, change), flow_settings)

        assert any("exactly 5 prerequisites" in p for p in problems)

    def test_prerequisite_count_comes_from_the_settings(self, valid_bundle, flow_settings):
        prerequisites, questions = make_prerequisites(3)
        bundle = valid_bundle | {"prerequisites": prerequisites, "prerequisite_questions": questions}

        assert problems_for(bundle, flow_settings | {"prerequisite_question_count": 3}) == []

    def test_rejects_a_prerequisite_question_for_an_unknown_prerequisite(self, valid_bundle, flow_settings):
        bundle = mutated(valid_bundle, lambda b: b["prerequisite_questions"][0].update(prerequisite="Something else"))

        problems = problems_for(bundle, flow_settings)

        assert any('refers to "Something else"' in p for p in problems)

    def test_rejects_a_prerequisite_without_exactly_one_question(self, valid_bundle, flow_settings):
        bundle = mutated(valid_bundle, lambda b: b["prerequisite_questions"][1].update(prerequisite="Prerequisite 1"))

        problems = problems_for(bundle, flow_settings)

        assert any('Prerequisite "Prerequisite 1" needs exactly one question' in p for p in problems)
        assert any('Prerequisite "Prerequisite 2" needs exactly one question' in p for p in problems)

    def test_rejects_repeated_prerequisites(self, valid_bundle, flow_settings):
        bundle = mutated(valid_bundle, lambda b: b["prerequisites"][1].update(name="prerequisite 1"))

        assert any("Prerequisites must be different" in p for p in problems_for(bundle, flow_settings))

    def test_rejects_a_different_number_of_questions_than_prerequisites(self, valid_bundle, flow_settings):
        bundle = mutated(valid_bundle, lambda b: b["prerequisite_questions"].pop())

        assert any("one prerequisite question per prerequisite" in p for p in problems_for(bundle, flow_settings))


class TestLatex:
    def test_reports_expressions_the_checker_cannot_parse(self, valid_bundle, flow_settings):
        bundle = mutated(valid_bundle, lambda b: b["diagnostic"][0].update(question="Solve $\\frac{1}{$ now."))
        latex = FakeLatex(bad=("\\frac{1}{",))

        problems = problems_for(bundle, flow_settings, latex)

        assert problems == ["LaTeX does not parse: '\\\\frac{1}{'"]

    def test_collects_maths_from_questions_and_options_of_both_quizzes(self, valid_bundle, flow_settings):
        def change(b):
            b["diagnostic"][0]["question"] = "Evaluate $x^2$."
            b["diagnostic"][1]["options"][0] = "$$y+1$$ is the value"
            b["prerequisite_questions"][0]["question"] = "What is $a+b$?"

        latex = FakeLatex()

        problems_for(mutated(valid_bundle, change), flow_settings, latex)

        assert sorted(latex.calls[0]) == ["a+b", "x^2", "y+1"]

    def test_does_not_call_the_checker_when_there_is_no_maths(self, valid_bundle, flow_settings):
        latex = FakeLatex()

        problems_for(valid_bundle, flow_settings, latex)

        assert latex.calls == []


class TestAssessmentGuard:
    def test_replaces_the_prerequisites_with_the_deterministic_ones(self):
        assessment = {"level": "beginner", "prerequisites_to_cover": ["invented"], "gaps": ["loops"]}
        covered = [{"name": "Arrays", "why_needed": "x"}, {"name": "Loops", "why_needed": "y"}]

        guarded = AssessmentGuard().apply(assessment, covered)

        assert guarded == {"level": "beginner", "prerequisites_to_cover": ["Arrays", "Loops"], "gaps": ["loops"]}

    def test_does_not_change_the_assessment_it_is_given(self):
        assessment = {"prerequisites_to_cover": ["invented"]}

        AssessmentGuard().apply(assessment, [])

        assert assessment == {"prerequisites_to_cover": ["invented"]}


class TestCompositeValidator:
    class Stub:
        def __init__(self, problems):
            self.problems, self.calls = problems, []

        def validate(self, subject, **context):
            self.calls.append((subject, context))
            return list(self.problems)

    def test_is_valid_when_every_part_is_valid(self):
        assert CompositeValidator([self.Stub([]), self.Stub([])]).validate({}) == []

    def test_reports_the_first_failing_part_and_skips_the_rest(self):
        first, second, third = self.Stub([]), self.Stub(["bad"]), self.Stub(["worse"])

        problems = CompositeValidator([first, second, third]).validate({"x": 1}, settings={"a": 1})

        assert problems == ["bad"]
        assert third.calls == []
        assert first.calls == [({"x": 1}, {"settings": {"a": 1}})]


class TestDiagnosticReviewValidator:
    def test_turns_reviewer_issues_into_problems_naming_the_question(self, valid_bundle):
        reviewer = lambda bundle: [("q4", "The hard question can be answered from its wording.")]  # noqa: E731

        problems = DiagnosticReviewValidator(reviewer).validate(valid_bundle)

        assert problems == ["Question q4: The hard question can be answered from its wording."]

    def test_is_valid_when_the_reviewer_finds_nothing(self, valid_bundle):
        assert DiagnosticReviewValidator(lambda bundle: []).validate(valid_bundle) == []
