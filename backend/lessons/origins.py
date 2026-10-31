"""Why a lesson was made, decided by the server (plan R23, T6).

A client may say "this lesson is a recommendation", but the word counts for nothing until it checks out: a recommended
lesson must point at the caller's own graded attempt and at a topic that attempt told them to revisit. A follow-up or a
quiz result can only come from the server's own features, so a client is never allowed to claim them here.
"""

import uuid
from dataclasses import dataclass

from rest_framework.exceptions import ValidationError

from graph.validators import TextRules
from quizzes.models import QuickQuiz, QuickQuizAttempt

from .models import Origin, TestSubmission


@dataclass(frozen=True)
class VerifiedOrigin:
    origin: str
    recommended_from: dict | None  # {attempt_id, topic}, as stored on the lesson


class OriginVerifier:
    #: the same words for an attempt that is missing, someone else's, or not graded, so none of them can be probed
    NOT_YOURS = "That is not one of your graded test attempts."
    NOT_YOUR_QUIZ_RESULT = "That is not one of your finished quizzes about a topic."

    def verify(self, user, origin: str, recommended_from) -> VerifiedOrigin:
        if origin == Origin.DIRECT:
            if recommended_from:
                raise self._refuse("recommended_from", "Only a recommended lesson says what it was recommended by.")
            return VerifiedOrigin(Origin.DIRECT.value, None)
        if origin == Origin.RECOMMENDATION:
            return VerifiedOrigin(Origin.RECOMMENDATION.value, self._recommendation(user, recommended_from))
        if origin == Origin.QUIZ_RESULT:
            return VerifiedOrigin(Origin.QUIZ_RESULT.value, self._quiz_result(user, recommended_from))
        if origin in Origin.values:
            raise self._refuse("origin", "That kind of lesson cannot be asked for here.")
        raise self._refuse("origin", f"{origin!r} is not a way a lesson can start.")

    def _recommendation(self, user, given) -> dict:
        if not isinstance(given, dict) or not given.get("attempt_id") or not str(given.get("topic") or "").strip():
            raise self._refuse("recommended_from", "Say which attempt and which topic recommended this lesson.")
        try:
            attempt_id = uuid.UUID(str(given["attempt_id"]))
        except ValueError:
            raise self._refuse("recommended_from", self.NOT_YOURS) from None
        attempt = TestSubmission.objects.filter(
            pk=attempt_id, lesson__owner=user, status=TestSubmission.Status.GRADED
        ).first()
        if attempt is None:
            raise self._refuse("recommended_from", self.NOT_YOURS)
        wanted = TextRules.norm(str(given["topic"]))
        topic = next(
            (t for t in (attempt.result or {}).get("topics_to_revisit") or [] if TextRules.norm(t) == wanted), None
        )
        if topic is None:
            raise self._refuse("recommended_from", "That attempt did not ask you to revisit that topic.")
        return {"attempt_id": str(attempt.pk), "topic": topic}

    def _quiz_result(self, user, given) -> dict:
        """A graded attempt at a quiz about a topic, owned by the caller. The same refusal for a missing one, someone
        else's, one that is not graded and one of a quiz made from lessons (which points at those lessons instead)."""
        try:
            attempt_id = uuid.UUID(str((given or {}).get("attempt_id")))
        except (ValueError, AttributeError):
            raise self._refuse("recommended_from", self.NOT_YOUR_QUIZ_RESULT) from None
        attempt = (
            QuickQuizAttempt.objects.select_related("quiz")
            .filter(
                pk=attempt_id,
                quiz__owner=user,
                quiz__source_type=QuickQuiz.SourceType.TOPIC,
                status=QuickQuizAttempt.Status.GRADED,
            )
            .first()
        )
        if attempt is None:
            raise self._refuse("recommended_from", self.NOT_YOUR_QUIZ_RESULT)
        return {"quiz_id": str(attempt.quiz_id), "attempt_id": str(attempt.pk), "topic": attempt.quiz.topic}

    @staticmethod
    def _refuse(field: str, message: str) -> ValidationError:
        return ValidationError({field: [message]})
