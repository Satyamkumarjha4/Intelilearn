"""From a weak concept to the page of its lesson that teaches it (plan §9.6, R18)."""

from collections.abc import Sequence

from graph.concept_index import ConceptIndex

from .models import Lesson


class ConceptLinks:
    """A link is `{concept, page, heading}`, the concept as it was asked for: `page` is empty when nothing could place
    it, and the learner is then sent to the lesson as a whole. A concept the index does not name (an old lesson's test
    wrote its concepts in the model's own words) is linked to the nearest one (`ConceptIndex.nearest`). A lesson made
    before the concept index existed has none stored, so its index is worked out from its plan and pages here (in
    memory: reading never writes); `ConceptIndexBackfill` stores them."""

    @staticmethod
    def index_of(lesson: Lesson | None) -> ConceptIndex:
        if lesson is None:
            return ConceptIndex()
        stored = ConceptIndex.from_json(lesson.concept_index)
        return stored if stored.entries else ConceptIndex.build(lesson.plan, lesson.pages)

    @classmethod
    def of(cls, lesson: Lesson | None, concepts: Sequence[str]) -> list[dict]:
        index = cls.index_of(lesson)
        links = []
        for concept in concepts:
            entry = index.nearest(concept)
            links.append(
                {"concept": concept, "page": entry.page if entry else "", "heading": entry.heading if entry else ""}
            )
        return links
