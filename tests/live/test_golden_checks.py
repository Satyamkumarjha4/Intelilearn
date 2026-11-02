"""Unit under test: `live.golden.LessonChecks`, what the golden-topic live suite checks in a finished lesson.

Why: the live suite is only worth running if its checks are right: one that passes a lesson with an empty page, or
fails a good one, makes a real-model run (slow and not free) meaningless. These tests run offline in `make check`.

Use cases:
- a complete lesson on the topic passes
- missing or thin pages, too few sections, and placeholder text are each reported by page
- a lesson that hardly mentions its topic is reported, and the keywords needed depend on the topic
- a test with too few questions, a single kind (a lesson test has at least multiple choice and multiple select),
  repeated ids or no marks is reported
- a missing document or incomplete stored code is reported
- too many degradation warnings are reported, and a topic that wants a picture needs one
- question quality (phase 9.8): a multiple-select question with fewer than two correct options, a numerical expression
  that does not evaluate or whose stored answer is not its value, and a short or long answer whose criteria do not add
  up to its marks are each reported by question; a good question of every kind passes
- a question about a lesson that names a concept the lesson does not have is reported, spelling and case aside
- the calibration pool must have two valid multiple-choice questions in each of the five bands
- the judged traits of a topic and the plan's quantitative flag are compared with what a person would say, and a model
  that did not answer is reported
- a retake's question that shares most of its words with an earlier one is reported, just under the product's own
  threshold too
- the revision sheet's coverage is measured with the product's rule: more than a third of the concepts missing fails
"""

import pytest
from live.golden import (
    GOLDEN_TOPICS,
    ConceptChecks,
    DedupeChecks,
    GoldenTopic,
    LessonChecks,
    PlanChecks,
    PoolChecks,
    QuestionChecks,
    SheetChecks,
    TraitChecks,
)
from support.lesson_data import make_final_test
from support.question_data import make_question

from graph.questions import TopicTraits

TOPIC = GoldenTopic("Binary search", ("sorted", "middle", "half"), min_keywords=2)
checks = LessonChecks()


def body(extra=""):
    return ("Binary search works on a sorted list by checking the middle item and discarding half. " * 8) + extra


def page(sections=3, words_text=None):
    return {
        "key": "x", "title": "T", "summary": "A short recap.",
        "sections": [{"id": f"s{n}", "heading": f"Part {n}", "body": words_text or body()} for n in range(sections)],
    }  # fmt: skip


def lesson(**over):
    base = {
        "pages": {key: page() for key in LessonChecks.PAGES},
        "final_test": make_final_test(),
        "code": "function LessonDocument() {}",
        "code_parts": {"pages": dict.fromkeys(LessonChecks.PAGES, "code"), "interactives": {}},
        "warnings": [],
        "media": 0,
    }
    return base | over


def test_a_complete_lesson_passes():
    assert checks.problems(lesson(), TOPIC) == []


def test_the_golden_topics_are_distinct_and_have_enough_keywords_to_be_demanding():
    topics = [g.topic for g in GOLDEN_TOPICS]

    assert len(set(topics)) == len(topics) >= 3
    assert all(len(g.keywords) >= g.min_keywords >= 2 for g in GOLDEN_TOPICS)


class TestPages:
    def test_a_missing_page_is_reported(self):
        pages = {k: page() for k in ("introduction", "core")}

        assert "The advanced page is missing." in checks.problems(lesson(pages=pages), TOPIC)

    def test_too_few_sections_and_a_thin_page_are_reported_for_that_page(self):
        pages = {"introduction": page(), "core": page(sections=2), "advanced": page(sections=3, words_text="Short.")}

        problems = checks.problems(lesson(pages=pages), TOPIC)

        assert "The core page has 2 sections; at least 3 are expected." in problems
        assert any(p.startswith("The advanced page is thin:") for p in problems)

    @pytest.mark.parametrize(
        "leak", ["Lorem ipsum dolor", "TODO write this", "As an AI language model I", "[insert example]"]
    )
    def test_placeholder_text_is_reported(self, leak):
        pages = {k: page() for k in LessonChecks.PAGES} | {"core": page(words_text=body(leak))}

        assert any("placeholder text" in p for p in checks.problems(lesson(pages=pages), TOPIC))

    def test_a_lesson_that_hardly_mentions_its_topic_is_reported(self):
        generic = "Learning is a process of understanding ideas and applying them carefully to problems. " * 12
        pages = {k: page(words_text=generic) for k in LessonChecks.PAGES}

        problems = checks.problems(lesson(pages=pages), TOPIC)

        assert any(p.startswith("The pages hardly mention Binary search") for p in problems)

    def test_the_keywords_needed_depend_on_the_topic(self):
        biology = GoldenTopic("Photosynthesis", ("chlorophyll", "glucose"), min_keywords=2)

        assert checks.problems(lesson(), biology)[0].startswith("The pages hardly mention Photosynthesis")


class TestTest:
    def test_too_few_questions_and_kinds_are_reported(self):
        few = {"questions": [q for q in make_final_test()["questions"] if q["type"] == "mcq"][:2]}

        problems = checks.problems(lesson(final_test=few), TOPIC)

        assert "The test has 2 questions; at least 8 are expected." in problems
        assert "The test uses fewer than 2 kinds of question." in problems

    def test_repeated_ids_and_a_test_worth_nothing_are_reported(self):
        questions = [dict(q, id="t1", marks=0) for q in make_final_test()["questions"]]

        problems = checks.problems(lesson(final_test={"questions": questions}), TOPIC)

        assert "The test has repeated question ids." in problems and "The test is worth no marks." in problems


class TestDocumentAndWarnings:
    def test_a_missing_document_and_incomplete_code_are_reported(self):
        problems = checks.problems(lesson(code="", code_parts={"pages": {"core": "x"}}), TOPIC)

        assert "The lesson has no document to show." in problems
        assert "The stored code does not hold the three reading pages." in problems

    def test_too_many_degradation_warnings_are_reported(self):
        warnings = [f"warning {n}" for n in range(4)]

        problems = checks.problems(lesson(warnings=warnings), TOPIC)

        assert problems[0].startswith(
            "The lesson came out with 4 degradation warnings: warning 0; warning 1; warning 2"
        )

    def test_a_topic_that_wants_a_picture_needs_one(self):
        wants = GoldenTopic("Amoeba", ("sorted", "middle"), wants_picture=True)

        assert checks.problems(lesson(), wants) == ["A lesson on Amoeba should have a real picture, and has none."]
        assert checks.problems(lesson(media=1), wants) == []


class TestQuestionQuality:
    quality = QuestionChecks()

    def test_a_good_question_of_every_kind_passes(self):
        questions = [
            make_question(kind, n)
            for n, kind in enumerate(("mcq", "msq", "numerical", "short_answer", "long_answer"), 1)
        ]

        assert self.quality.problems(questions) == []

    def test_a_multiple_select_question_needs_two_correct_options(self):
        question = make_question("msq", 1) | {"correct_indices": [1]}

        (problem,) = self.quality.problems([question])

        assert "1 correct option(s)" in problem and problem.startswith("t1 (msq)")

    def test_a_multiple_select_question_cannot_have_every_option_right(self):
        question = make_question("msq", 1)
        question["correct_indices"] = list(range(len(question["options"])))

        assert "every option is correct" in self.quality.problems([question])[0]

    def test_an_mcq_with_a_correct_index_outside_its_options_or_repeated_options_is_reported(self):
        outside = make_question("mcq", 1) | {"correct_index": 9}
        repeated = make_question("mcq", 2) | {"options": ["same", "same", "x", "y"]}

        problems = self.quality.problems([outside, repeated])

        assert any("correct_index is not one of its options" in p for p in problems)
        assert any("two options are the same" in p for p in problems)

    def test_a_numerical_expression_that_does_not_evaluate_is_reported(self):
        question = make_question("numerical", 1) | {"answer_expr": "sqrt(-1)"}

        assert "does not evaluate" in self.quality.problems([question])[0]

    def test_a_numerical_answer_that_is_not_its_expressions_value_is_reported(self):
        question = make_question("numerical", 1) | {"answer": 99}

        assert "is not the value of" in self.quality.problems([question])[0]

    @pytest.mark.parametrize("kind", ["short_answer", "long_answer"])
    def test_criteria_must_add_up_to_the_marks(self, kind):
        question = make_question(kind, 1)
        question["criteria"][0]["marks"] += 1

        (problem,) = self.quality.problems([question])

        assert f"add up to {question['marks'] + 1}, not its {question['marks']} marks" in problem

    def test_a_written_answer_without_criteria_or_a_model_answer_is_reported(self):
        question = make_question("short_answer", 1) | {"criteria": [], "model_answer": " "}

        problems = self.quality.problems([question])

        assert any("no criteria" in p for p in problems) and any("no model answer" in p for p in problems)


class TestConcepts:
    def test_a_question_naming_one_of_the_lessons_concepts_passes_whatever_its_spelling(self):
        questions = [{"id": "t1", "concept": "  halving THE range"}]

        assert ConceptChecks.problems(questions, ["Halving the range"]) == []

    def test_another_concept_is_reported_by_question(self):
        questions = [{"id": "t1", "concept": "Photosynthesis"}, {"id": "t2", "concept": "Halving the range"}]

        assert ConceptChecks.problems(questions, ["Halving the range"]) == [
            "t1 names the concept 'Photosynthesis', which the lesson does not have"
        ]


class TestPool:
    def pool(self):
        return [
            {"id": f"q{n}", "band": band, "options": list("abcd"), "correct_index": 1}
            for n, band in enumerate(
                [b for b in ("basic", "easy_moderate", "moderate", "moderate_hard", "hard") for _ in (0, 1)]
            )
        ]

    def test_two_valid_questions_in_every_band_pass(self):
        assert PoolChecks().problems(self.pool()) == []

    def test_a_missing_band_an_unknown_band_and_a_bad_question_are_reported(self):
        pool = self.pool()[1:]
        pool[0]["band"] = "ultra"
        pool[1]["options"] = ["only", "two"]

        problems = PoolChecks().problems(pool)

        assert any("band 'basic' has 0 questions" in p for p in problems)
        assert any("no known band" in p for p in problems)
        assert any("is not a valid multiple-choice question" in p for p in problems)


class TestJudgements:
    def test_traits_that_match_what_a_person_would_say_pass(self):
        judged = {topic: TopicTraits(q, p) for topic, q, p in TraitChecks.EXPECTED}

        assert TraitChecks().problems(judged) == []

    def test_a_wrong_judgement_and_a_silent_model_are_reported(self):
        judged = {topic: TopicTraits(q, p) for topic, q, p in TraitChecks.EXPECTED}
        judged["Quadratic equations"] = TopicTraits(False, False)
        del judged["Python list comprehensions"]

        problems = TraitChecks().problems(judged)

        assert "'Quadratic equations': judged quantitative=False, programming=False; expected True, False" in problems
        assert "'Python list comprehensions': the model did not answer" in problems

    def test_the_plans_flag_is_compared_per_topic(self):
        flags = {"Solving quadratic equations": True, "The causes of the French Revolution": True}

        assert PlanChecks().problems(flags) == [
            "'The causes of the French Revolution': the plan says quantitative=True, expected False"
        ]


class TestDedupe:
    earlier = [{"id": "t1", "question": "What does binary search do to the range of a sorted list at each step?"}]

    def test_a_new_question_passes(self):
        later = [{"id": "t1", "question": "Why must the list be sorted before searching?"}]

        assert DedupeChecks().problems(self.earlier, later) == []

    def test_a_reworded_repeat_is_reported_even_under_the_products_threshold(self):
        later = [{"id": "t4", "question": "How does binary search narrow the range of a sorted list at each step?"}]

        (problem,) = DedupeChecks().problems(self.earlier, later)

        assert problem.startswith("t4 shares ") and "with a question asked before" in problem


class TestSheetCoverage:
    content = {
        "subtopics": [
            {"title": "Halving", "summary": "Halve the range each step.", "key_points": ["Sorted data needed"],
             "common_mistakes": [], "worked_examples": []},
        ]
    }  # fmt: skip

    def test_the_concepts_the_sheet_never_mentions_are_listed(self):
        assert SheetChecks().missing(self.content, ["Halving the range", "Time complexity"]) == ["Time complexity"]

    def test_more_than_a_third_missing_fails_and_a_third_or_less_passes(self):
        concepts = ["Halving the range", "Sorted data", "Gardening", "Astronomy"]

        assert SheetChecks().problems(self.content, concepts[:3]) == []
        assert "misses 2 of 4 concepts: Gardening; Astronomy" in SheetChecks().problems(self.content, concepts)[0]
