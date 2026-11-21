"""Fixtures for the live suite: real models, real media services, the real sandbox. Run by hand: `pytest -m live`.

They spend money, using the keys in the environment (`.env`): each lesson is checked against `LIVE_MAX_COST_USD`
(default 2.00) from the `ModelCall` log, after it has run. The tests are skipped, with the reason, when the key is
missing. Nothing here runs under a plain `pytest` or `make check`.
"""

import os

import pytest


@pytest.fixture(autouse=True)
def _need_keys(request):
    """Live tests only: every other test in this folder (the offline checks) runs as usual."""
    if request.node.get_closest_marker("live") and not os.environ.get("GEMINI_API_KEY"):
        pytest.skip("GEMINI_API_KEY is not set: the default registry's models need it (see docs/process/testing.md)")


@pytest.fixture
def real_registry(db):
    """The default registry (Gemini, with Groq Llama as fallback) loaded into the test database."""
    from lessons.checkpoints import CheckpointerFactory
    from llm_registry.seed import DefaultRegistry
    from llm_registry.serialization import RegistrySerializer

    RegistrySerializer().load(DefaultRegistry().build())
    CheckpointerFactory().setup()  # the checkpoint tables are not Django models, so the test database lacks them


@pytest.fixture
def learner(db):
    from accounts.models import User

    user = User.objects.create_user("golden@example.com", password="not-used-by-the-suite", name="Golden")
    profile = user.profile
    profile.education_level, profile.learning_preference, profile.goal = "undergraduate", "mixed", "deep_understanding"
    profile.save()
    return user


@pytest.fixture
def max_cost() -> float:
    return float(os.environ.get("LIVE_MAX_COST_USD", "2.00"))


def answer_diagnostic(lesson, right: int = 5) -> None:
    """Get the first `right` questions right so the learner is routed to a lesson, not a study sheet."""
    from lessons.models import Quiz
    from lessons.services import QuizService
    from lessons.tasks import InlineTaskQueue

    quiz = Quiz.objects.get(lesson=lesson, kind="diagnostic")
    answers = {
        q["id"]: q["correct_index"] if n < right else (q["correct_index"] + 1) % len(q["options"])
        for n, q in enumerate(quiz.questions)
    }
    QuizService(queue=InlineTaskQueue()).submit(lesson, "diagnostic", answers)


@pytest.fixture
def built_lesson(real_registry, learner):
    """Builds a lesson on a topic from its first question to a ready lesson, with the real models."""
    from lessons.models import Stage
    from lessons.services import LessonService
    from lessons.tasks import InlineTaskQueue

    def build(topic: str):
        lesson, _ = LessonService(queue=InlineTaskQueue()).create(learner, topic)
        lesson.refresh_from_db()
        assert lesson.stage == Stage.AWAITING_DIAGNOSTIC, lesson.error
        answer_diagnostic(lesson)
        lesson.refresh_from_db()
        return lesson

    return build


@pytest.fixture
def rated_lesson(real_registry, learner):
    """Builds a lesson from a self-rating, with no quick check: the cheapest way to a ready lesson with real models."""
    from lessons.services import LessonService
    from lessons.stages import Entry, Stage
    from lessons.tasks import InlineTaskQueue

    def build(topic: str, halves: int = 6):
        lesson, _ = LessonService(queue=InlineTaskQueue()).create(
            learner, topic, entry=Entry.SELF_RATING, self_rating_halves=halves
        )
        lesson.refresh_from_db()
        assert lesson.stage == Stage.READY, f"{lesson.stage}: {lesson.error}"
        return lesson

    return build
