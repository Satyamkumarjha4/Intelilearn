"""What to do next after a quiz attempt, worked out in code from its score card (plan §11.4, D18).

A quiz about a topic offers to become a lesson ("Create a lesson for this"). A quiz made from lessons says which of
them to study, with the concepts that lost marks, the lesson that lost most first. (Deep links to the right page of the
lesson arrive with concept tags in phase 9.7; for now the advice points at the lesson.)
"""

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
        lost: dict[str, list[tuple[int, int, str]]] = {}
        for order, row in enumerate(rows):
            marks = row["marks"] - row["awarded"]
            if marks > 0 and source_of.get(row["id"]):
                lost.setdefault(source_of[row["id"]], []).append((marks, order, row["concept"]))
        details = {str(s.lesson_ref): s for s in quiz.sources.all()}
        advice = []
        for key, entries in lost.items():
            source = details.get(key)
            topics = list(dict.fromkeys(concept for _, _, concept in sorted(entries, key=lambda e: (-e[0], e[1]))))
            advice.append({
                "lesson_id": key if source and source.lesson_id else None,
                "title": source.title if source else "",
                "level": source.level if source else "",
                "marks_lost": sum(marks for marks, _, _ in entries),
                "topics": topics,
            })  # fmt: skip
        return sorted(advice, key=lambda item: (-item["marks_lost"], item["title"]))
