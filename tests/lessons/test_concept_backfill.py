"""Unit under test: `lessons.concept_backfill.ConceptIndexBackfill` and the `backfill_concept_index` command: writing
the concept index of lessons made before it existed (plan §9.6, R18).

Why: a quiz result sends a learner to the page that teaches a weak concept, from the lesson's concept index. New lessons
get theirs when they are made; the lessons already in the database have none, and their pages carry no tags, so the
index is worked out from the stored plan and pages by heading match. It must be safe to run any number of times and on a
live database: it only fills an empty index, never replaces one, never touches a lesson's other columns or its
`updated_at`, and says how many concepts it could and could not place so a person can judge the result. A lesson it
cannot place anything for still works: its links go to the lesson with no page.

Use cases:
- a lesson from before the index (no tags) gets an index placed by heading match, with the plan's notes as summaries
- the report counts the lessons it indexed, the lessons it skipped (no plan or no pages), and the concepts placed and
  not placed
- a concept whose heading is gone from the page is counted as not placed and listed without a page
- a lesson that already has an index is left exactly as it is
- running it again changes nothing and reports nothing new to index
- a dry run reports what it would do and writes nothing
- only the index is written: no other column and not `updated_at`
- the command prints the report, and `--dry-run` says nothing was written
"""

import io

import pytest
from django.core.management import call_command
from support.lesson_data import make_pages, make_plan

from lessons.concept_backfill import ConceptIndexBackfill
from lessons.models import Lesson

pytestmark = pytest.mark.django_db


@pytest.fixture
def old_lesson(make_ready_lesson):
    """A lesson made before the index: pages with no tags, and no stored index."""
    lesson = make_ready_lesson("Binary search")
    pages = make_pages(make_plan())
    for page in pages.values():
        for section in page["sections"]:
            section.pop("concepts", None)
    Lesson.objects.filter(pk=lesson.pk).update(pages=pages, concept_index=[])
    return Lesson.objects.get(pk=lesson.pk)


class TestRun:
    def test_an_old_lesson_gets_its_index_placed_by_heading(self, old_lesson):
        ConceptIndexBackfill().run()

        index = Lesson.objects.get(pk=old_lesson.pk).concept_index
        assert len(index) == 9
        assert index[0] == {
            "concept": "Searching a list", "page": "introduction", "heading": "Searching a list",
            "summary": "Explain Searching a list.",
        }  # fmt: skip

    def test_the_report_counts_lessons_and_concepts(self, old_lesson, make_lesson):
        make_lesson(topic="Plan only")  # a lesson that never got a plan
        gone = Lesson.objects.get(pk=old_lesson.pk)
        pages = gone.pages
        pages["advanced"]["sections"] = pages["advanced"]["sections"][:1]  # two concepts lost their sections
        Lesson.objects.filter(pk=gone.pk).update(pages=pages)

        report = ConceptIndexBackfill().run()

        assert (report.lessons_seen, report.lessons_indexed, report.lessons_skipped) == (2, 1, 1)
        assert (report.concepts_placed, report.concepts_unplaced) == (7, 2)
        assert not report.dry_run

    def test_a_concept_whose_section_is_gone_is_listed_without_a_page(self, old_lesson):
        pages = old_lesson.pages
        pages["core"]["sections"].pop(1)  # "The loop invariant"
        Lesson.objects.filter(pk=old_lesson.pk).update(pages=pages)

        ConceptIndexBackfill().run()

        entry = next(
            row for row in Lesson.objects.get(pk=old_lesson.pk).concept_index if row["concept"] == "The loop invariant"
        )
        assert (entry["page"], entry["heading"]) == ("", "")

    @pytest.mark.parametrize("fields", [{"plan": None}, {"pages": None}])
    def test_a_lesson_without_a_plan_or_pages_is_skipped(self, old_lesson, fields):
        Lesson.objects.filter(pk=old_lesson.pk).update(**fields)

        report = ConceptIndexBackfill().run()

        assert (report.lessons_indexed, report.lessons_skipped) == (0, 1)
        assert Lesson.objects.get(pk=old_lesson.pk).concept_index == []

    def test_an_index_that_exists_is_left_as_it_is(self, old_lesson):
        kept = [{"concept": "Mine", "page": "core", "heading": "H", "summary": "S"}]
        Lesson.objects.filter(pk=old_lesson.pk).update(concept_index=kept)

        report = ConceptIndexBackfill().run()

        assert report.lessons_seen == 0
        assert Lesson.objects.get(pk=old_lesson.pk).concept_index == kept

    def test_running_it_again_changes_nothing(self, old_lesson):
        ConceptIndexBackfill().run()
        first = Lesson.objects.get(pk=old_lesson.pk).concept_index

        again = ConceptIndexBackfill().run()

        assert again.lessons_seen == 0 and again.lessons_indexed == 0
        assert Lesson.objects.get(pk=old_lesson.pk).concept_index == first

    def test_a_dry_run_reports_and_writes_nothing(self, old_lesson):
        report = ConceptIndexBackfill().run(dry_run=True)

        assert report.dry_run and report.lessons_indexed == 1 and report.concepts_placed == 9
        assert Lesson.objects.get(pk=old_lesson.pk).concept_index == []

    def test_only_the_index_is_written(self, old_lesson):
        before = Lesson.objects.get(pk=old_lesson.pk)

        ConceptIndexBackfill().run()

        after = Lesson.objects.get(pk=old_lesson.pk)
        assert after.updated_at == before.updated_at
        assert (after.pages, after.plan, after.stage) == (
            before.pages, before.plan, before.stage,
        )  # fmt: skip


class TestTheCommand:
    def run(self, *args) -> str:
        out = io.StringIO()
        call_command("backfill_concept_index", *args, stdout=out)
        return out.getvalue()

    def test_it_prints_the_counts(self, old_lesson):
        text = self.run()

        assert "1 lesson indexed" in text and "9 concepts placed" in text and "0 not placed" in text
        assert Lesson.objects.get(pk=old_lesson.pk).concept_index

    def test_a_dry_run_says_nothing_was_written(self, old_lesson):
        text = self.run("--dry-run")

        assert "Dry run" in text and "nothing was written" in text and "1 lesson would be indexed" in text
        assert Lesson.objects.get(pk=old_lesson.pk).concept_index == []

    def test_with_nothing_to_do_it_says_so(self):
        assert "Nothing to index" in self.run()
