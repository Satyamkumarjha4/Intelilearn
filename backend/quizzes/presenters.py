"""A quiz and its attempts as the API shows them: plain dicts that the serializers format."""

from graph.levels import StarRating
from graph.scoring import AttemptTrend
from lessons.models import GraphRun

from .attempts import QuizAttemptService
from .models import QuickQuiz, QuickQuizAttempt
from .recommendations import QuizRecommendations


class QuizPresenter:
    def __init__(self, attempts: QuizAttemptService | None = None, recommendations: QuizRecommendations | None = None):
        self.attempts = attempts or QuizAttemptService()
        self.recommendations = recommendations or QuizRecommendations()

    # --- the quiz ------------------------------------------------------------------------------------------------

    def summary(self, quiz: QuickQuiz) -> dict:
        """One row of the learner's list. Reads `quiz.attempts` (prefetch it for a page)."""
        attempts = sorted(quiz.attempts.all(), key=lambda a: a.attempt_no)
        scored = [a for a in attempts if a.status == QuickQuizAttempt.Status.GRADED and a.available]
        percents = [self._percent(a) for a in scored]
        return {
            "id": quiz.id,
            "topic": quiz.topic,
            "source_type": quiz.source_type,
            "stage": quiz.stage,
            "level": quiz.level,
            "num_questions": quiz.config["num_questions"],
            "attempts_count": len(attempts),
            "latest_score": percents[-1] if percents else None,
            "best_score": max(percents) if percents else None,
            "created_at": quiz.created_at,
            "updated_at": quiz.updated_at,
        }

    def detail(self, quiz: QuickQuiz) -> dict:
        history = self.attempts.history(quiz)
        open_attempt = self.attempts.open(quiz)
        halves = quiz.config.get("self_rating_halves")
        graded = any(a["status"] == QuickQuizAttempt.Status.GRADED for a in history["attempts"])
        return {
            **self.summary_without_attempts(quiz),
            "error": quiz.error,
            "level_source": (quiz.assessment or {}).get("source", ""),
            "config": {
                "num_questions": quiz.config["num_questions"],
                "types": quiz.config["types"],
                "level_mode": quiz.config["level_mode"],
                "self_rating": StarRating(halves).stars if halves else None,
            },
            "sources": [
                {"lesson_id": s.lesson_id, "title": s.title, "level": s.level, "share": s.share}
                for s in quiz.sources.all()
            ],
            "attempts": history["attempts"],
            "trend": history["trend"],
            "open_attempt": None
            if open_attempt is None
            else {"id": open_attempt.id, "attempt_no": open_attempt.attempt_no, "status": open_attempt.status},
            "run_id": self.active_run_id(quiz),
            "can_create_lesson": quiz.source_type == QuickQuiz.SourceType.TOPIC and graded,
        }

    def summary_without_attempts(self, quiz: QuickQuiz) -> dict:
        row = self.summary(quiz)
        return {key: row[key] for key in ("id", "topic", "source_type", "stage", "level", "created_at", "updated_at")}

    @staticmethod
    def active_run_id(quiz: QuickQuiz):
        """The run that is making or retaking the quiz now, if one is going."""
        runs = GraphRun.objects.for_subject(quiz).filter(
            graph=GraphRun.Graph.QUICK_QUIZ, status__in=[GraphRun.Status.QUEUED, GraphRun.Status.RUNNING]
        )
        return runs.order_by("-created_at").values_list("pk", flat=True).first()

    # --- an attempt ----------------------------------------------------------------------------------------------

    def attempt(self, quiz: QuickQuiz, attempt: QuickQuizAttempt) -> dict:
        """One attempt: while it is open, its questions without answer keys and the answers saved so far (so a refresh
        resumes); once it is over, the same questions, the learner's answers, the score card and what to do next."""
        open_questions = self.attempts.shown_questions(attempt)
        return {
            "id": attempt.id,
            "attempt_no": attempt.attempt_no,
            "status": attempt.status,
            "error": attempt.error,
            "questions": open_questions or self.attempts.sealed_questions(attempt),
            "total_marks": sum(q["marks"] for q in attempt.questions) if open_questions else attempt.available,
            "answers": attempt.answers,
            "result": attempt.result if not attempt.is_open else None,
            "awarded": attempt.awarded,
            "available": attempt.available,
            "band": attempt.band,
            "duration_s": attempt.duration_s,
            "recommendations": self.recommendations.of(quiz, attempt),
            "started_at": attempt.started_at,
            "submitted_at": attempt.submitted_at,
            "graded_at": attempt.graded_at,
        }

    @staticmethod
    def _percent(attempt: QuickQuizAttempt) -> int:
        return AttemptTrend.percent(attempt.awarded, attempt.available)
