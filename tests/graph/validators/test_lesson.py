"""Unit under test: `graph.validators.lesson`: `PlanValidator`, `PageValidator`, `QuestionBatchValidator` and
`InteractivePlanValidator`, the deterministic rules for Stage B output.

Why: these gate what a learner is taught. A plan whose pages repeat each other, an introduction that skips a missing
prerequisite, a batch of questions whose types differ from the cells it was asked for, or an interactive anchored to a
section that does not exist all parse as valid JSON, so only these rules catch them. Their messages are also the
feedback the model gets on its retry.

Use cases:
- a well-formed plan, page, test and interactive plan have no problems
- plan: exactly the three page keys, outlines of 2 to 8 parts, no concept on two pages
- plan: the introduction lists every prerequisite to cover (names compared ignoring case and punctuation)
- plan: carries only the quantitative flag; the test is the fixed blueprint, so there is no test spec to check
- page: the key matches the plan, 2 to 8 sections, unique ids and headings, a real body, every outline concept taught
- page: a Python snippet must parse, and LaTeX the checker cannot parse is reported
- question batch: one question for each cell, in order, of the cell's type and difficulty; questions are unique and mcq
  and msq options sane; short and long criteria add up to the marks; a numerical expression computes and its answer was
  stored; LaTeX is checked
- interactive plan: unique valid ids, anchors that exist, a media_query for images and GIFs, a purpose that names the
  concept, at least one per page and no more than the maximum
"""

import copy

import pytest
from support.fakes import FakeSandbox
from support.lesson_data import make_blueprint_test, make_interactive_plan, make_page, make_pages, make_plan

from graph.questions import LessonTestBlueprint
from graph.validators import InteractivePlanValidator, PageValidator, PlanValidator, QuestionBatchValidator

SETTINGS = {"max_interactives_per_page": 3}


def mutated(data, change):
    data = copy.deepcopy(data)
    change(data)
    return data


class TestPlan:
    def problems(self, plan, to_cover=()):
        return PlanValidator().validate(plan, prerequisites_to_cover=list(to_cover))

    def test_a_well_formed_plan_has_no_problems(self):
        assert self.problems(make_plan()) == []

    def test_needs_exactly_the_three_page_keys(self):
        plan = mutated(make_plan(), lambda p: p["pages"].pop())

        assert any("Plan exactly three pages" in p for p in self.problems(plan))

    def test_a_concept_may_only_be_on_one_page(self):
        plan = mutated(make_plan(), lambda p: p["pages"][1]["outline"][0].update(concept="searching a list!"))

        assert any("repeated across pages" in p and "searching a list" in p for p in self.problems(plan))

    @pytest.mark.parametrize("keep", [1, 9])
    def test_each_outline_has_two_to_eight_parts(self, keep):
        def change(plan):
            item = plan["pages"][0]["outline"][0]
            plan["pages"][0]["outline"] = [{**item, "concept": f"c{n}"} for n in range(keep)]

        assert any(
            'Page "introduction" needs 2-8 outline parts' in p for p in self.problems(mutated(make_plan(), change))
        )

    def test_the_introduction_must_cover_every_prerequisite_to_cover(self):
        plan = make_plan(prerequisites=["Arrays"])
        needed = [{"name": "Arrays", "why_needed": "x"}, {"name": "Loops", "why_needed": "y"}]

        found = self.problems(plan, needed)

        assert found == [
            'The introduction must cover the prerequisite "Loops" (list it in covers_prerequisites and teach it in '
            "the outline)."
        ]

    def test_prerequisite_names_match_ignoring_case_and_punctuation(self):
        plan = make_plan(prerequisites=["arrays!"])

        assert self.problems(plan, [{"name": "Arrays", "why_needed": "x"}]) == []

    def test_the_plan_has_no_test_spec_to_check(self):
        assert "final_test" not in make_plan() and "quantitative" in make_plan()
        assert self.problems(make_plan(quantitative=False)) == []


class TestPage:
    def problems(self, page, plan=None, key="core", latex=None):
        plan = plan or make_plan()
        plan_page = next(p for p in plan["pages"] if p["key"] == key)
        return PageValidator(latex).validate(page, plan_page=plan_page)

    def test_a_well_formed_page_has_no_problems(self):
        assert self.problems(make_page("core")) == []

    def test_the_key_must_match_the_plan(self):
        assert any('must have key "core"' in p for p in self.problems(make_page("advanced"), key="core"))

    @pytest.mark.parametrize("keep", [1, 9])
    def test_two_to_eight_sections(self, keep):
        def change(page):
            section = page["sections"][0]
            page["sections"] = [{**section, "id": f"s{n}", "heading": f"H{n}"} for n in range(keep)]

        assert any("Write 2-8 sections" in p for p in self.problems(mutated(make_page("core"), change)))

    def test_section_ids_and_headings_are_unique(self):
        def change(page):
            page["sections"][1].update(id="s1", heading="halving the range")

        found = self.problems(mutated(make_page("core"), change))

        assert any("Section ids must be unique" in p for p in found)
        assert any("Section headings must be unique" in p for p in found)

    def test_a_section_needs_a_real_body(self):
        page = mutated(make_page("core"), lambda p: p["sections"][0].update(body="Too short."))

        assert any('Section "Halving the range" is too thin' in p for p in self.problems(page))

    def test_every_outline_concept_must_be_taught(self):
        def change(page):
            page["sections"][2].update(heading="Something else", body="Unrelated words about gardens. " * 10)

        found = self.problems(mutated(make_page("core"), change))

        assert any("missing: Returning the index" in p for p in found)

    def test_python_snippets_must_parse(self):
        def change(page):
            page["sections"][0]["code_snippets"] = [
                {"language": "python", "code": "def f(:\n  pass", "explanation": "x"}
            ]

        found = self.problems(mutated(make_page("core"), change))

        assert any('The code in "Halving the range" is not valid Python' in p for p in found)

    def test_other_languages_are_not_parsed(self):
        def change(page):
            page["sections"][0]["code_snippets"] = [{"language": "cpp", "code": "int main( {", "explanation": "x"}]

        assert self.problems(mutated(make_page("core"), change)) == []

    def test_unparseable_latex_is_reported(self):
        checker = FakeSandbox(latex_errors=["LaTeX does not parse: 'bad'"])

        assert self.problems(make_page("core"), latex=checker) == ["LaTeX does not parse: 'bad'"]

    def test_formulas_workings_and_body_maths_are_all_checked(self):
        def change(page):
            page["sections"][1]["body"] += " Use $a+b$."
            page["sections"][1]["worked_examples"] = [{"problem": "Compute $c$", "solution": "Then $d$"}]

        checker = FakeSandbox()

        self.problems(mutated(make_page("core"), change), latex=checker)

        assert {"a+b", "c", "d"} <= set(checker.latex_calls[0])


class TestQuestionBatch:
    CELLS = LessonTestBlueprint.for_topic(True).cells

    def problems(self, questions, cells=CELLS, latex=None):
        return QuestionBatchValidator(latex).validate(questions, cells=cells)

    def test_a_well_formed_batch_has_no_problems(self):
        assert self.problems(make_blueprint_test()["questions"]) == []

    def test_one_question_is_needed_for_each_cell(self):
        questions = make_blueprint_test()["questions"][:9]

        assert any(
            "Write exactly 10 questions, one for each cell, in order; there are 9" in p
            for p in self.problems(questions)
        )

    def test_a_question_of_another_type_than_its_cell_is_named(self):
        def change(questions):
            questions[0].update(type="msq", options=["a", "b", "c", "d"], correct_indices=[0, 1])

        found = self.problems(mutated(make_blueprint_test()["questions"], change))

        assert any("Question t1 must be a mcq question; it is a msq" in p for p in found)

    def test_a_question_of_another_difficulty_than_its_cell_is_named(self):
        found = self.problems(mutated(make_blueprint_test()["questions"], lambda qs: qs[0].update(difficulty="expert")))

        assert any("Question t1 must be easy; it is expert" in p for p in found)

    def test_a_multiple_select_question_needs_different_options(self):
        def change(questions):
            msq = next(q for q in questions if q["type"] == "msq")
            msq["options"][1] = msq["options"][0]

        assert any(
            "options must all be different" in p
            for p in self.problems(mutated(make_blueprint_test()["questions"], change))
        )

    def test_a_numerical_expression_that_cannot_be_computed_is_reported(self):
        def change(questions):
            numerical = next(q for q in questions if q["type"] == "numerical")
            numerical["answer_expr"] = "1 / 0"

        found = self.problems(mutated(make_blueprint_test()["questions"], change))

        assert any("answer_expr cannot be computed" in p for p in found)

    def test_a_numerical_answer_that_was_never_computed_is_reported(self):
        def change(questions):
            numerical = next(q for q in questions if q["type"] == "numerical")
            del numerical["answer"]

        assert any(
            "answer was not computed" in p for p in self.problems(mutated(make_blueprint_test()["questions"], change))
        )

    def test_questions_must_not_repeat_and_ids_must_be_unique(self):
        def change(questions):
            questions[1].update(id="t1", question=questions[0]["question"])

        found = self.problems(mutated(make_blueprint_test()["questions"], change))

        assert any("Question ids must be unique" in p for p in found)
        assert any("Questions must not repeat" in p for p in found)

    def test_an_mcq_may_not_use_a_catch_all_option(self):
        questions = mutated(
            make_blueprint_test()["questions"], lambda qs: qs[0]["options"].__setitem__(3, "None of the above")
        )

        assert any("all/none of the above" in p for p in self.problems(questions))

    def test_latex_in_questions_is_checked(self):
        questions = mutated(make_blueprint_test()["questions"], lambda qs: qs[0].update(question="Solve $x^$."))

        assert self.problems(questions, latex=FakeSandbox(latex_errors=["bad latex"])) == ["bad latex"]

    def test_a_batch_of_a_few_cells_is_checked_against_only_those_cells(self):
        questions = make_blueprint_test()["questions"][4:6]

        assert self.problems(questions, cells=self.CELLS[4:6]) == []


class TestInteractivePlan:
    def problems(self, plan, pages=None):
        return InteractivePlanValidator().validate(plan, pages=pages or make_pages(), settings=SETTINGS)

    def test_a_well_formed_plan_has_no_problems(self):
        assert self.problems(make_interactive_plan()) == []

    def test_ids_must_be_unique_and_simple(self):
        def change(plan):
            plan["specs"][1]["id"] = plan["specs"][0]["id"]
            plan["specs"][2]["id"] = "bad id!"

        found = self.problems(mutated(make_interactive_plan(), change))

        assert any("Interactive ids must be unique" in p for p in found)
        assert any('Interactive id "bad id!" must be letters, digits and underscores' in p for p in found)

    def test_an_anchor_must_be_a_section_of_its_page(self):
        plan = mutated(make_interactive_plan(), lambda p: p["specs"][0].update(anchor_section="s99"))

        assert any(
            'anchors to section "s99", which doesn\'t exist on the introduction page' in p for p in self.problems(plan)
        )

    @pytest.mark.parametrize("kind", ["image", "gif"])
    def test_media_needs_a_search_query(self, kind):
        plan = mutated(make_interactive_plan(), lambda p: p["specs"][0].update(kind=kind, media_query=" "))

        assert any(f"is an {kind}: give it a media_query" in p for p in self.problems(plan))

    def test_the_purpose_must_say_what_it_teaches(self):
        plan = mutated(make_interactive_plan(), lambda p: p["specs"][0].update(purpose="Cool."))

        assert any("say which concept it teaches" in p for p in self.problems(plan))

    def test_every_page_needs_at_least_one_and_at_most_the_maximum(self):
        def change(plan):
            first = plan["specs"][0]
            plan["specs"] = [{**first, "id": f"w{n}"} for n in range(4)] + [plan["specs"][1]]

        found = self.problems(mutated(make_interactive_plan(), change))

        assert "Give the advanced page at least one interactive." in found
        assert any("introduction page has 4 interactives; at most 3 are allowed" in p for p in found)
