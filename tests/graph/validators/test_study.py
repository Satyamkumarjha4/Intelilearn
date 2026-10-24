"""Unit under test: `graph.validators.study.StudyMaterialValidator`, the rules a generated cheat, revision or practice
sheet must satisfy before it is saved.

Why: these sheets are the whole product for a learner who aced the diagnostic. A cheat sheet that is a wall of text, a
revision sheet that skips half the topic, or a practice sheet whose questions are not graded easy to hard is useless,
and nothing downstream checks them: the sheets are rendered by fixed templates, not reviewed by a person.

Use cases:
- a well-formed sheet of each kind has no problems
- a cheat sheet needs 2+ sections, 6 to 40 items and a formula for every formula item
- a revision sheet needs 4+ subtopics, each with a real summary and 3+ key points
- a practice sheet needs 15 to 25 questions, ordered easy to hard, of at least 3 types, with unique questions
- an mcq with a catch-all option, and a Python reference solution that does not parse, are refused
- the sheet must cover the diagnostic's concepts (a third may be missing)
- LaTeX the checker cannot parse is reported
- an unknown kind is a problem, not a crash
"""

import copy

import pytest
from support.fakes import FakeSandbox
from support.study_data import CONCEPTS, make_cheat_sheet, make_practice_sheet, make_revision_sheet

from graph.validators import StudyMaterialValidator


def problems(kind, content, concepts=CONCEPTS, latex=None):
    return StudyMaterialValidator(latex).validate(content, kind=kind, concepts=concepts)


@pytest.mark.parametrize(
    ("kind", "make"),
    [
        ("cheat_sheet", make_cheat_sheet),
        ("revision_sheet", make_revision_sheet),
        ("practice_sheet", make_practice_sheet),
    ],
)
def test_a_well_formed_sheet_has_no_problems(kind, make):
    assert problems(kind, make()) == []


class TestCheatSheet:
    def test_needs_at_least_two_sections(self):
        sheet = make_cheat_sheet()
        sheet["sections"] = sheet["sections"][:1]
        sheet["sections"][0]["items"] += sheet["sections"][0]["items"]

        assert "Use at least 2 sections." in problems("cheat_sheet", sheet)

    def test_needs_at_least_six_items(self):
        sheet = make_cheat_sheet()
        sheet["sections"][1]["items"] = sheet["sections"][1]["items"][:1]

        assert any("at least 6 items; it has 5" in p for p in problems("cheat_sheet", sheet))

    def test_is_refused_when_far_too_long(self):
        sheet = make_cheat_sheet()
        sheet["sections"][0]["items"] = sheet["sections"][0]["items"] * 11

        assert any("at most 40 items" in p for p in problems("cheat_sheet", sheet))

    def test_a_formula_item_needs_its_formula(self):
        sheet = make_cheat_sheet()
        sheet["sections"][0]["items"][0]["formula"] = ""

        assert any('"Item 1" is a formula item but has no formula' in p for p in problems("cheat_sheet", sheet))


class TestRevisionSheet:
    def test_needs_at_least_four_subtopics(self):
        sheet = make_revision_sheet()
        sheet["subtopics"] = sheet["subtopics"][:3]

        assert any("at least 4 are needed; there are 3" in p for p in problems("revision_sheet", sheet))

    def test_each_subtopic_needs_a_real_summary_and_three_key_points(self):
        sheet = make_revision_sheet()
        sheet["subtopics"][0]["summary"] = "Too short."
        sheet["subtopics"][1]["key_points"] = ["only one"]

        found = problems("revision_sheet", sheet)

        assert any("needs a fuller summary" in p and CONCEPTS[1] in p for p in found)
        assert any("needs at least 3 key points" in p for p in found)


class TestPracticeSheet:
    @pytest.mark.parametrize("count", [14, 26])
    def test_has_between_fifteen_and_twenty_five_questions(self, count):
        assert any("15-25 questions" in p for p in problems("practice_sheet", make_practice_sheet(count)))

    @pytest.mark.parametrize("count", [15, 25])
    def test_the_bounds_are_allowed(self, count):
        assert problems("practice_sheet", make_practice_sheet(count)) == []

    def test_must_be_ordered_from_easy_to_hard(self):
        sheet = make_practice_sheet()
        sheet["questions"].reverse()

        assert "Order the questions from easy to hard." in problems("practice_sheet", sheet)

    def test_must_mix_at_least_three_types(self):
        sheet = make_practice_sheet()
        for question in sheet["questions"]:
            if question["type"] == "short_answer":
                question.update(type="mcq", options=["a", "b", "c", "d"], correct_index=0)

        assert "Mix at least 3 question types." in problems("practice_sheet", sheet)

    def test_questions_must_not_repeat(self):
        sheet = make_practice_sheet()
        sheet["questions"][1]["question"] = sheet["questions"][0]["question"]

        assert any("must not repeat" in p for p in problems("practice_sheet", sheet))

    def test_refuses_a_catch_all_option_in_an_mcq(self):
        sheet = make_practice_sheet()
        mcq = next(q for q in sheet["questions"] if q["type"] == "mcq")
        mcq["options"][3] = "All of the above"

        assert any("all/none of the above" in p for p in problems("practice_sheet", sheet))

    def test_refuses_a_python_reference_solution_that_does_not_parse(self):
        sheet = make_practice_sheet()
        sheet["questions"][-1] |= {
            "type": "code", "language": "python", "starter_code": "", "reference_solution": "def f(:\n  pass",
            "test_cases": [{"input": "1", "expected_output": "1"}],
        }  # fmt: skip

        assert any("reference solution is not valid Python" in p for p in problems("practice_sheet", sheet))


class TestCoverage:
    def test_a_missing_concept_is_tolerated_up_to_a_third(self):
        concepts = [*CONCEPTS, "Unrelated topic"]  # 1 of 3 missing is within a third

        assert problems("cheat_sheet", make_cheat_sheet(), concepts=concepts) == []

    def test_too_many_missing_concepts_are_named(self):
        concepts = ["Quantum entanglement", "Photosynthesis", "Halving the range"]

        found = problems("cheat_sheet", make_cheat_sheet(), concepts=concepts)

        assert any("Cover the topic's key concepts" in p and "Quantum entanglement" in p for p in found)

    def test_there_is_nothing_to_cover_without_concepts(self):
        assert problems("revision_sheet", make_revision_sheet(), concepts=[]) == []


class TestLatex:
    def test_unparseable_maths_is_reported_for_each_kind(self):
        message = "LaTeX does not parse: '\\frac{1}{'"
        checker = FakeSandbox(latex_errors=[message])
        cheat, revision, practice = make_cheat_sheet(), make_revision_sheet(), make_practice_sheet()
        revision["subtopics"][0]["summary"] += " Use $x^2$ here."
        practice["questions"][0]["question"] += " Evaluate $y$."

        for kind, content in [("cheat_sheet", cheat), ("revision_sheet", revision), ("practice_sheet", practice)]:
            assert problems(kind, content, latex=checker) == [message], kind

    def test_a_cheat_sheet_checks_its_formulas_and_symbols(self):
        checker = FakeSandbox()

        problems("cheat_sheet", make_cheat_sheet(), latex=checker)

        assert "\\log_2 n" in checker.latex_calls[0] and "n" in checker.latex_calls[0]

    def test_without_a_checker_nothing_is_asked(self):
        sheet = copy.deepcopy(make_cheat_sheet())

        assert problems("cheat_sheet", sheet, latex=None) == []


def test_an_unknown_kind_is_a_problem_not_a_crash():
    assert problems("wallpaper", {}) == ["Unknown study material kind 'wallpaper'."]
