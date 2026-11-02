"""Unit under test: `lessons.concept_links.ConceptLinks`: the link from a weak concept to the page of its lesson that
teaches it (plan §9.6, R18).

Why: "Study this" must open the page that teaches the concept, not just the lesson. The answer is the lesson's concept
index, written when the lesson was made. A lesson from before the index has none, so the index is worked out from its
plan and pages on the spot; and a concept nothing can place (or one the lesson never taught) links to the lesson with
no page, which opens the lesson as a whole. Nothing here asks a model or writes to the database.

Use cases:
- a concept in the stored index links to its page and the heading of the section that teaches it
- the name is matched ignoring case and spacing
- a lesson with no stored index gets one worked out from its plan and pages, without saving it
- a concept the lesson's index lists but could not place links to the lesson with no page
- a concept the lesson does not know links to the lesson with no page, keeping the name as given
- a lesson with no plan, or no pages, links every concept to the lesson with no page
- a lesson that was deleted (no lesson at all) links every concept with no page
"""

import pytest

from lessons.concept_links import ConceptLinks

pytestmark = pytest.mark.django_db


class TestLinks:
    def test_a_concept_in_the_stored_index_links_to_its_page_and_section(self, make_ready_lesson):
        lesson = make_ready_lesson("Binary search")
        lesson.concept_index = [
            {"concept": "Halving the range", "page": "core", "heading": "How halving works", "summary": "s"}
        ]

        links = ConceptLinks.of(lesson, ["Halving the range"])

        assert links == [{"concept": "Halving the range", "page": "core", "heading": "How halving works"}]

    def test_the_name_is_matched_ignoring_case_and_spacing(self, make_ready_lesson):
        lesson = make_ready_lesson("Binary search")
        lesson.concept_index = [{"concept": "Halving the range", "page": "core", "heading": "H", "summary": ""}]

        assert ConceptLinks.of(lesson, ["  halving   THE range"])[0]["page"] == "core"

    def test_a_lesson_with_no_stored_index_gets_one_from_its_plan_and_pages(self, make_ready_lesson):
        lesson = make_ready_lesson("Binary search")
        assert lesson.concept_index == []

        links = ConceptLinks.of(lesson, ["The loop invariant", "Time complexity"])

        assert links == [
            {"concept": "The loop invariant", "page": "core", "heading": "The loop invariant"},
            {"concept": "Time complexity", "page": "advanced", "heading": "Time complexity"},
        ]
        lesson.refresh_from_db()
        assert lesson.concept_index == []  # worked out for this answer, not saved by a read

    def test_a_concept_the_index_could_not_place_has_no_page(self, make_ready_lesson):
        lesson = make_ready_lesson("Binary search")
        lesson.concept_index = [{"concept": "Sorted data", "page": "", "heading": "", "summary": ""}]

        assert ConceptLinks.of(lesson, ["Sorted data"]) == [{"concept": "Sorted data", "page": "", "heading": ""}]

    def test_a_concept_the_lesson_does_not_know_has_no_page_and_keeps_its_name(self, make_ready_lesson):
        lesson = make_ready_lesson("Binary search")

        assert ConceptLinks.of(lesson, ["Photosynthesis"]) == [{"concept": "Photosynthesis", "page": "", "heading": ""}]

    @pytest.mark.parametrize("fields", [{"plan": None}, {"pages": None}])
    def test_a_lesson_without_a_plan_or_pages_links_every_concept_without_a_page(self, make_ready_lesson, fields):
        lesson = make_ready_lesson("Binary search")
        for name, value in fields.items():
            setattr(lesson, name, value)

        assert ConceptLinks.of(lesson, ["Time complexity"]) == [
            {"concept": "Time complexity", "page": "", "heading": ""}
        ]

    def test_a_lesson_that_is_gone_links_every_concept_without_a_page(self):
        assert ConceptLinks.of(None, ["A", "B"]) == [
            {"concept": "A", "page": "", "heading": ""},
            {"concept": "B", "page": "", "heading": ""},
        ]
