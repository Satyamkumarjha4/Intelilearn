"""Writing the concept index of lessons made before it existed (plan §9.6, R18)."""

from dataclasses import dataclass

from graph.concept_index import ConceptIndex

from .models import Lesson


@dataclass(frozen=True)
class BackfillReport:
    lessons_seen: int  # lessons with an empty index
    lessons_indexed: int  # of those, the ones that have a plan and pages to place concepts on
    lessons_skipped: int  # the rest: no plan or no pages (a lesson that is only sheets, or that never finished)
    concepts_placed: int  # concepts found on a page of their lesson
    concepts_unplaced: int  # concepts listed without a page: their link opens the lesson as a whole
    dry_run: bool = False

    def lines(self) -> list[str]:
        if not self.lessons_seen:
            return ["Nothing to index: every lesson already has its concept index."]
        verb = "would be indexed" if self.dry_run else "indexed"
        noun = "lesson" if self.lessons_indexed == 1 else "lessons"
        lines = [
            f"{self.lessons_indexed} {noun} {verb}, {self.lessons_skipped} skipped (no plan or no pages).",
            f"{self.concepts_placed} concepts placed, {self.concepts_unplaced} not placed.",
        ]
        return ["Dry run: nothing was written.", *lines] if self.dry_run else lines


class ConceptIndexBackfill:
    """Builds the index of every lesson that has none from its stored plan and pages: a concept is placed by the section
    whose heading is the outline's heading (old pages carry no tags), else by the section that talks about it. Safe to
    run again and on a live database: it fills only empty indexes, writes only that column, and does not touch
    `updated_at`."""

    def run(self, *, dry_run: bool = False) -> BackfillReport:
        seen = indexed = skipped = placed = unplaced = 0
        for lesson in Lesson.objects.filter(concept_index=[]).only("id", "plan", "pages").iterator(chunk_size=200):
            seen += 1
            index = ConceptIndex.build(lesson.plan, lesson.pages) if lesson.plan and lesson.pages else ConceptIndex()
            if not index.entries:
                skipped += 1
                continue
            indexed += 1
            placed += index.placed
            unplaced += index.unplaced
            if not dry_run:
                Lesson.objects.filter(pk=lesson.pk, concept_index=[]).update(concept_index=index.to_json())
        return BackfillReport(seen, indexed, skipped, placed, unplaced, dry_run)
