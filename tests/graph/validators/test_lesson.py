"""Unit under test: `graph.validators.lesson`: `PlanValidator`, `PageValidator`, `FinalTestValidator` and
`InteractivePlanValidator`, the deterministic rules for Stage B output.

Why: these gate what a learner is taught. A plan whose pages repeat each other, an introduction that skips a missing
prerequisite, a test whose mix differs from the plan, or an interactive anchored to a section that does not exist all
parse as valid JSON, so only these rules catch them. Their messages are also the feedback the model gets on its retry.

Use cases:
- a well-formed plan, page, test and interactive plan have no problems
- plan: exactly the three page keys, outlines of 2 to 8 parts, no concept on two pages
- plan: the introduction lists every prerequisite to cover (names compared ignoring case and punctuation)
- plan: the test spec is within the configured count and its type and difficulty mixes add up, with 3+ types
- page: the key matches the plan, 2 to 8 sections, unique ids and headings, a real body, every outline concept taught
- page: a Python snippet must parse, and LaTeX the checker cannot parse is reported
- final test: the question, type and difficulty counts match the spec; questions are unique and mcq options sane
- interactive plan: unique valid ids, anchors that exist, a media_query for images and GIFs, a purpose that names the
  concept, at least one per page and no more than the maximum
"""

import copy

import pytest
from support.fakes import FakeSandbox
from support.lesson_data import make_final_test, make_interactive_plan, make_page, make_pages, make_plan

from graph.validators import FinalTestValidator, InteractivePlanValidator, PageValidator, PlanValidator

SETTINGS = {"final_test_min": 10, "final_test_max": 15, "max_interactives_per_page": 3}


def mutated(data, change):
    data = copy.deepcopy(data)
    change(data)
    return data


class TestPlan:
    def problems(self, plan, to_cover=()):
        return PlanValidator().validate(plan, settings=SETTINGS, prerequisites_to_cover=list(to_cover))

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

    @pytest.mark.parametrize("count", [9, 16])
    def test_the_test_has_the_configured_number_of_questions(self, count):
        plan = mutated(make_plan(), lambda p: p["final_test"].update(question_count=count))

        assert any("The final test must have 10-15 questions" in p for p in self.problems(plan))

    def test_the_mixes_must_add_up_to_the_count(self):
        def change(plan):
            plan["final_test"]["type_mix"]["mcq"] += 1
            plan["final_test"]["difficulty_mix"]["easy"] -= 1

        found = self.problems(mutated(make_plan(), change))

        assert any("type_mix adds up to 11, not question_count 10" in p for p in found)
        assert any("difficulty_mix adds up to 9, not question_count 10" in p for p in found)

    def test_at_least_three_question_types(self):
        def change(plan):
            plan["final_test"]["type_mix"] = {"mcq": 6, "numerical": 4, "short_answer": 0, "long_answer": 0, "code": 0}

        assert any("Mix at least 3 question types" in p for p in self.problems(mutated(make_plan(), change)))


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


class TestFinalTest:
    SPEC = make_plan()["final_test"]

    def problems(self, test, latex=None):
        return FinalTestValidator(latex).validate(test, spec=self.SPEC)

    def test_a_well_formed_test_has_no_problems(self):
        assert self.problems(make_final_test()) == []

    def test_the_question_count_must_match(self):
        test = mutated(make_final_test(), lambda t: t["questions"].pop())

        assert any("Write exactly 10 questions; there are 9" in p for p in self.problems(test))

    def test_the_type_mix_must_match(self):
        def change(test):
            test["questions"][0].update(type="short_answer", model_answer="a", key_points=["p"])

        found = self.problems(mutated(make_final_test(), change))

        assert any("exactly 4 mcq questions; there are 3" in p for p in found)
        assert any("exactly 2 short_answer questions; there are 3" in p for p in found)

    def test_the_difficulty_mix_must_match(self):
        test = mutated(make_final_test(), lambda t: t["questions"][0].update(difficulty="hard"))

        assert any("exactly 4 easy questions; there are 3" in p for p in self.problems(test))

    def test_questions_must_not_repeat_and_ids_must_be_unique(self):
        def change(test):
            test["questions"][1].update(id="t1", question=test["questions"][0]["question"])

        found = self.problems(mutated(make_final_test(), change))

        assert any("Question ids must be unique" in p for p in found)
        assert any("Questions must not repeat" in p for p in found)

    def test_an_mcq_may_not_use_a_catch_all_option(self):
        test = mutated(make_final_test(), lambda t: t["questions"][0]["options"].__setitem__(3, "None of the above"))

        assert any("all/none of the above" in p for p in self.problems(test))

    def test_latex_in_questions_is_checked(self):
        test = mutated(make_final_test(), lambda t: t["questions"][0].update(question="Solve $x^$."))

        assert self.problems(test, latex=FakeSandbox(latex_errors=["bad latex"])) == ["bad latex"]


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
