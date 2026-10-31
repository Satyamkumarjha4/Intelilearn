"""Fixtures for tests that need a quick quiz (registered for every test through tests/conftest.py): `make_quiz` and
`quiz`
(a ready topic quiz owned by `user`), and `make_attempt`. The models are imported inside the fixtures, because this
module
is loaded before Django is set up."""

import pytest


@pytest.fixture
def make_quiz(user):
    from graph.quiz_config import QuizConfig
    from quizzes.models import QuickQuiz
    from quizzes.stages import QuizStage

    default = QuizConfig(10, ("mcq",), "self_rating", 6)

    def _make(**fields):
        config = fields.pop("config", default)
        topic = fields.setdefault("topic", "Binary search")
        fields.setdefault("owner", user)
        fields.setdefault("source_type", "topic")
        fields.setdefault("stage", QuizStage.READY)
        return QuickQuiz.objects.create(
            config=config.as_dict(), config_hash=config.hash(fields["source_type"], [topic]), **fields
        )

    return _make


@pytest.fixture
def quiz(make_quiz):
    return make_quiz()


@pytest.fixture
def make_attempt():
    from quizzes.models import QuickQuizAttempt

    def _make(quiz, **fields):
        number = fields.pop("attempt_no", quiz.attempts.count() + 1)
        return QuickQuizAttempt.objects.create(quiz=quiz, attempt_no=number, **fields)

    return _make


@pytest.fixture
def make_ready_lesson(user):
    """A lesson with pages, as a quiz needs it: ready, with a plan, pages and a level. Made a day apart, oldest"
    " first."""
    from datetime import UTC, datetime, timedelta

    from lessons.models import Lesson, Stage
    from support.lesson_data import make_pages, make_plan

    made = []

    def _make(topic="Binary search", level="foundation", **fields):
        plan = make_plan() | {"title": topic}
        owner = fields.pop("owner", user)
        lesson = Lesson.objects.create(owner=owner, topic=topic)
        fields = {"route": "lesson"} | fields
        Lesson.objects.filter(pk=lesson.pk).update(
            stage=Stage.READY, title=topic, level=level, plan=plan, pages=make_pages(plan),
            created_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=len(made)), **fields,
        )  # fmt: skip
        made.append(lesson.pk)
        return Lesson.objects.get(pk=lesson.pk)

    return _make


@pytest.fixture
def traits_for():
    """A topic traits service whose judge answers with the traits given (None: it fails), cached in memory."""
    from graph.questions.traits import TopicTraits
    from quizzes.traits import TopicTraitsService, TraitsCache, TraitsUnavailable
    from support.fakes import FakeTopicTraits

    class Memory:
        def __init__(self):
            self.data = {}

        def get(self, key, default=None):
            return self.data.get(key, default)

        def set(self, key, value, timeout=None):
            self.data[key] = value

    maths = TopicTraits(quantitative=True, programming=False)

    def _make(traits=maths):
        judge = FakeTopicTraits(traits if traits is not None else TraitsUnavailable("down"))
        service = TopicTraitsService(model=judge, cache=TraitsCache(Memory()))
        service.judge = judge
        return service

    return _make
