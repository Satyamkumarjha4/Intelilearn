"""Unit under test: `graph.concept_index.ConceptIndex`: the list of a lesson's concepts and the page and section that
teach each (plan §7.1, §9.6, R18).

Why: a quiz result says which concepts a learner got wrong, and the app links each to the page that teaches it. The
link is only as good as this index, so it is built in code (no model) from the lesson's plan, the one place that says
which page a concept belongs to, and from what the pages really contain: a section the page writer tagged with the
concept, else the section whose heading is the outline's heading, else a section that talks about the concept. A
concept that cannot be placed is still listed, without a page, so the link falls back to the lesson. Old lessons have
no tags, and their pages may have been written with other headings, so they go through the same rules.

Use cases:
- a tagged section places its concept: the page is the plan's page, the heading the section's
- a concept with no tag is placed by the section whose heading matches the outline's heading (any case or spacing)
- a concept with neither is placed by the section that talks about it
- a concept that no section covers is listed without a page or a heading
- a tag the plan does not know is ignored; a tag on a page other than the concept's own page does not place it there
- every outline concept is listed once, in teaching order, with the outline's notes as its summary
- a concept that appears twice in the plan is listed once
- a lesson with no pages (or no plan) has an index of unplaced concepts (or none)
- the index is read back from JSON as it was written; stored data that is not an index is read as empty
- a concept is found by its name whatever its case or spacing, and an unknown name is not found
- the names, and how many concepts were placed and how many not
"""

import pytest
from support.lesson_data import make_pages, make_plan

from graph.concept_index import ConceptEntry, ConceptIndex


class TestPlacing:
    def test_a_tagged_section_places_its_concept(self):
        plan = make_plan()
        pages = make_pages(plan)
        pages["core"]["sections"][0]["heading"] = "A different heading"
        pages["core"]["sections"][0]["concepts"] = ["Halving the range"]

        entry = ConceptIndex.build(plan, pages).find("Halving the range")

        assert entry == ConceptEntry("Halving the range", "core", "A different heading", "Explain Halving the range.")

    def test_a_concept_without_a_tag_is_placed_by_the_outline_heading(self):
        plan = make_plan()
        pages = make_pages(plan)
        pages["core"]["sections"][1]["heading"] = "  THE loop   invariant "
        for page in pages.values():
            for section in page["sections"]:
                section["concepts"] = []

        entry = ConceptIndex.build(plan, pages).find("The loop invariant")

        assert (entry.page, entry.heading) == ("core", "  THE loop   invariant ")

    def test_a_concept_with_neither_is_placed_by_the_section_that_talks_about_it(self):
        plan = make_plan()
        pages = make_pages(plan)
        section = pages["advanced"]["sections"][2]
        section["heading"] = "Binary search over results"
        section["body"] = "Here we look at searching on answers instead of positions. " * 10

        entry = ConceptIndex.build(plan, pages).find("Searching on answers")

        assert (entry.page, entry.heading) == ("advanced", "Binary search over results")

    def test_a_concept_no_section_covers_has_no_page(self):
        plan = make_plan()
        pages = make_pages(plan)
        pages["advanced"]["sections"].pop(1)  # "Off-by-one pitfalls" is gone from the page

        entry = ConceptIndex.build(plan, pages).find("Off-by-one pitfalls")

        assert entry == ConceptEntry("Off-by-one pitfalls", "", "", "Explain Off-by-one pitfalls.")

    def test_a_tag_the_plan_does_not_know_places_nothing(self):
        plan = make_plan()
        pages = make_pages(plan)
        pages["core"]["sections"][0]["concepts"] = ["Something made up"]

        index = ConceptIndex.build(plan, pages)

        assert index.find("Something made up") is None
        assert index.find("Halving the range").page == "core"  # still placed, by its heading

    def test_a_tag_on_the_wrong_page_does_not_move_a_concept(self):
        plan = make_plan()
        pages = make_pages(plan)
        pages["introduction"]["sections"][0]["concepts"] = ["Time complexity"]  # a concept of the advanced page

        entry = ConceptIndex.build(plan, pages).find("Time complexity")

        assert (entry.page, entry.heading) == ("advanced", "Time complexity")


class TestWhatIsListed:
    def test_every_outline_concept_once_in_teaching_order(self):
        plan = make_plan()

        index = ConceptIndex.build(plan, make_pages(plan))

        assert index.names() == [
            "Searching a list", "Sorted data", "Why halving helps",
            "Halving the range", "The loop invariant", "Returning the index",
            "Time complexity", "Off-by-one pitfalls", "Searching on answers",
        ]  # fmt: skip
        assert {e.summary for e in index.entries} >= {"Explain Sorted data."}

    def test_a_concept_the_plan_repeats_is_listed_once(self):
        plan = make_plan()
        plan["pages"][1]["outline"].append(dict(plan["pages"][0]["outline"][0]))

        assert ConceptIndex.build(plan, make_pages(plan)).names().count("Searching a list") == 1

    def test_without_pages_the_concepts_are_listed_unplaced(self):
        index = ConceptIndex.build(make_plan(), None)

        assert len(index.entries) == 9
        assert index.placed == 0 and index.unplaced == 9

    def test_without_a_plan_there_is_nothing_to_list(self):
        assert ConceptIndex.build(None, make_pages()).entries == ()
        assert ConceptIndex.build({}, {}).entries == ()


class TestStoring:
    def test_it_is_read_back_as_it_was_written(self):
        plan = make_plan()
        index = ConceptIndex.build(plan, make_pages(plan))

        assert ConceptIndex.from_json(index.to_json()) == index

    def test_the_stored_form_is_a_list_of_concept_page_heading_summary(self):
        plan = make_plan()
        stored = ConceptIndex.build(plan, make_pages(plan)).to_json()

        assert stored[0] == {
            "concept": "Searching a list", "page": "introduction", "heading": "Searching a list",
            "summary": "Explain Searching a list.",
        }  # fmt: skip

    @pytest.mark.parametrize("stored", [None, {}, "x", 3, [1, 2], [{"concept": "a"}], [{"concept": 1, "page": "core"}]])
    def test_stored_data_that_is_not_an_index_is_read_as_empty(self, stored):
        assert ConceptIndex.from_json(stored).entries == ()

    def test_an_entry_missing_only_its_summary_is_kept(self):
        stored = [{"concept": "a", "page": "core", "heading": "A"}]

        assert ConceptIndex.from_json(stored).find("a") == ConceptEntry("a", "core", "A", "")


class TestFinding:
    def test_a_concept_is_found_by_its_name_whatever_the_case_or_spacing(self):
        plan = make_plan()
        index = ConceptIndex.build(plan, make_pages(plan))

        assert index.find("  the LOOP invariant").concept == "The loop invariant"

    def test_an_unknown_name_is_not_found(self):
        plan = make_plan()

        assert ConceptIndex.build(plan, make_pages(plan)).find("Photosynthesis") is None
        assert ConceptIndex.build(plan, make_pages(plan)).find("") is None


class TestCounting:
    def test_placed_and_unplaced(self):
        plan = make_plan()
        pages = make_pages(plan)
        pages["advanced"]["sections"] = pages["advanced"]["sections"][:1]

        index = ConceptIndex.build(plan, pages)

        assert (index.placed, index.unplaced) == (7, 2)
