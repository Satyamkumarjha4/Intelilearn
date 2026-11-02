"""What to do next after a quiz attempt, worked out in code from its score card (plan §11.4, D18).

A quiz about a topic offers to become a lesson ("Create a lesson for this"). A quiz made from lessons says which of
them to study, the lesson that lost most first, and for each the concepts that lost marks with a link to the page of the
lesson that teaches the concept (`ConceptLinks`: the concept index, else the plan and pages). A concept that cannot be
placed links to the lesson with no page; a lesson that was deleted since is named and marked deleted.
"""

from graph.grading import ScoreCard
from lessons.concept_links import ConceptLinks

from .models import QuickQuiz, QuickQuizAttempt


class QuizRecommendations:
    def of(self, quiz: QuickQuiz, attempt: QuickQuizAttempt) -> dict | None:
        """None until the attempt is graded."""
        if attempt.status != QuickQuizAttempt.Status.GRADED or not attempt.result:
            return None
        if quiz.source_type == QuickQuiz.SourceType.TOPIC:
            return {"kind": "topic", "topics": list(attempt.result.get("topics_to_revisit") or []), "lessons": []}
        return {"kind": "lessons", "topics": [], "lessons": self._lessons(quiz, attempt)}

    def _lessons(self, quiz: QuickQuiz, attempt: QuickQuizAttempt) -> list[dict]:
        source_of = {q["id"]: q.get("source", "") for q in attempt.questions}
        rows = [row for row in attempt.result.get("questions") or [] if row.get("awarded") is not None]
        by_lesson: dict[str, list[dict]] = {}
        for row in rows:
            if source_of.get(row["id"]):
                by_lesson.setdefault(source_of[row["id"]], []).append(row)
        details = {str(s.lesson_ref): s for s in quiz.sources.select_related("lesson")}
        advice = []
        for key, lesson_rows in by_lesson.items():
            topics = ScoreCard.topics_to_revisit(lesson_rows)
            if not topics:
                continue  # this lesson lost nothing
            source = details.get(key)
            lesson = source.lesson if source else None
            lost = self._lost_by_concept(lesson_rows)
            links = ConceptLinks.of(lesson, topics)
            advice.append({
                "lesson_id": key if lesson else None,
                "title": source.title if source else "",
                "level": source.level if source else "",
                "marks_lost": sum(lost.values()),
                "topics": topics,
                "links": [{**link, "marks_lost": lost[topic]} for link, topic in zip(links, topics, strict=True)],
                "deleted": lesson is None,
            })  # fmt: skip
        return sorted(advice, key=lambda item: (-item["marks_lost"], item["title"]))

    @staticmethod
    def _lost_by_concept(rows: list[dict]) -> dict[str, int]:
        lost: dict[str, int] = {}
        for row in rows:
            lost[row["concept"]] = lost.get(row["concept"], 0) + row["marks"] - row["awarded"]
        return lost
