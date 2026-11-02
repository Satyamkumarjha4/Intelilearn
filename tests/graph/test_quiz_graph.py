"""Unit under test: the `quick_quiz` graph (`graph.builders.QuickQuizGraphBuilder`): a quiz's questions, for the first
attempt and for every retake.

Why: the nodes pass their own tests; the wiring decides that a rating, the scores and the calibration walk each lead to
the same questions pipeline, that the walk pauses the graph exactly once and carries on from where it left off, that a
retake neither asks for the level again nor repeats a question, and that an attempt only starts when its set is ready. A
quiz from lessons must be written lesson by lesson, each at its own level, from their summaries and nothing more.

Use cases:
- a self-rated topic quiz skips the walk, writes the cells of its blueprint in batches of five, starts the waiting
  attempt with the questions in order and makes the quiz ready
- a quiz from two lessons using their scores writes each lesson's questions from that lesson's summary only, at that
  lesson's level, and tags each question with its lesson
- a quiz from lessons writes each question about one of its own lesson's concepts, listed in the prompt under that
  lesson, so a weak concept can be linked to the lesson's page; a lesson with a concept index is summarised from the
  index, one without from its plan
- the calibration walk writes a pool with no prerequisite half, keeps it on the quiz, pauses the graph for the learner;
  after the walk the level comes from the ladder and the quiz is built, with the stage going calibration → preparing
  → ready
- a pool that keeps failing its rules ends the run with the reason, before any question is written
- a retake knows the level already, does not walk again, and is given every question the quiz has asked as ones not to
  repeat
- a quiz that was deleted or stopped (no waiting attempt) fails the run; so does a quiz whose lesson was deleted
- a quiz that cannot be filled whole keeps the questions it has, with a warning; one with none fails
"""

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from support.fixtures import budget_snapshot
from support.lesson_data import make_plan
from support.question_data import ScriptedQuestions, make_question
from support.quiz_data import make_questions

from graph.builders import QuickQuizGraphBuilder
from graph.difficulty_mix import DifficultyMix
from graph.errors import RunFailed
from graph.levels import Level
from graph.questions import QuestionConcepts
from graph.quiz_config import QuizConfig
from graph.schemas import DiagnosticBundle, QuestionBatch
from quizzes.models import QuickQuiz, QuickQuizAttempt, QuickQuizSource
from quizzes.stages import QuizStage

pytestmark = pytest.mark.django_db(transaction=True)


class QuizRun:
    """Drives the compiled graph the way `FlowRunner` does for a quiz: stream, remember the nodes and the interrupt."""

    def __init__(self, quiz, attempt, ctx):
        self.quiz, self.attempt, self.ctx = quiz, attempt, ctx
        self.graph = QuickQuizGraphBuilder().build(InMemorySaver())
        self.config = {"configurable": {"thread_id": str(quiz.id)}}
        self.nodes, self.interrupt = [], None

    def stream(self, payload):
        self.interrupt = None
        for _mode, chunk in self.graph.stream(payload, self.config, context=self.ctx, stream_mode=["updates"]):
            for node, update in chunk.items():
                if node == "__interrupt__":
                    self.interrupt = update[0].value
                else:
                    self.nodes.append(node)
        return self

    def start(self):
        return self.stream({"quiz_id": str(self.quiz.id), "attempt_id": str(self.attempt.id)})

    def resume(self):
        return self.stream(Command(resume=True))

    def state(self):
        return self.graph.get_state(self.config).values


@pytest.fixture
def questions(gateway):
    scripted = ScriptedQuestions()
    gateway.respond("test.generate", scripted)
    return scripted


@pytest.fixture
def build(make_quiz, make_lesson, flow_settings, ctx):
    """A quiz as the service leaves it: preparing, with one waiting attempt, and `lessons` lessons it is made from."""

    def _build(*, mode="self_rating", count=10, types=("mcq",), levels=(), stage=QuizStage.PREPARING, **fields):
        config = QuizConfig(count, tuple(types), mode, 6 if mode == "self_rating" else None)
        quiz = make_quiz(
            config=config, stage=stage, source_type="lessons" if levels else "topic", config_snapshot=budget_snapshot(),
            settings_snapshot=flow_settings, **fields,
        )  # fmt: skip
        shares = {0: count} if len(levels) <= 1 else None
        for number, level in enumerate(levels):
            lesson = make_lesson(topic=f"Lesson {number}")
            plan = make_plan() | {
                "title": f"Lesson {number}",
                "summary": f"SUMMARY-{number}: what lesson {number} covers.",
            }
            type(lesson).objects.filter(pk=lesson.pk).update(plan=plan, level=level)
            share = (shares or {}).get(number, count // len(levels))
            QuickQuizSource.objects.create(
                quiz=quiz, lesson=lesson, lesson_ref=lesson.pk, title=f"Lesson {number}", level=level, share=share
            )
        attempt = QuickQuizAttempt.objects.create(quiz=quiz, attempt_no=1, status="generating", questions=[])
        return QuizRun(quiz, attempt, ctx)

    return _build


def pool_bundle():
    return DiagnosticBundle(diagnostic=make_questions(), prerequisites=[], prerequisite_questions=[]).model_dump()


class TestARatedTopicQuiz:
    def test_it_writes_the_blueprint_in_batches_and_starts_the_attempt(self, build, questions, gateway):
        run = build().start()

        assert run.nodes == [
            "load_quiz", "resolve_source", "level_from_rating", "plan_quiz", "plan_batches", "generate_questions",
            "generate_questions", "questions_join", "persist_attempt",
        ]  # fmt: skip
        attempt = QuickQuizAttempt.objects.get(pk=run.attempt.pk)
        assert attempt.status == "in_progress" and [q["id"] for q in attempt.questions] == [
            f"t{n}" for n in range(1, 11)
        ]
        assert QuickQuiz.objects.get(pk=run.quiz.pk).stage == QuizStage.READY
        assert len(gateway.called("test.generate")) == 2

    def test_the_difficulties_are_the_mix_of_the_learners_level(self, build, questions):
        run = build().start()

        mix = DifficultyMix.for_level(Level.FOUNDATION, 10)  # three stars is Foundation
        attempt = QuickQuizAttempt.objects.get(pk=run.attempt.pk)
        for difficulty, wanted in mix.counts.items():
            assert sum(1 for q in attempt.questions if q["difficulty"] == difficulty.value) == wanted

    def test_the_level_is_kept_on_the_quiz_and_the_model_is_told_it(self, build, questions, gateway):
        run = build().start()

        assert QuickQuiz.objects.get(pk=run.quiz.pk).level == "foundation"
        assert "foundation" in gateway.called("test.generate")[0].messages[1].content

    def test_the_calls_are_logged_against_the_quiz_not_a_lesson(self, build, questions, gateway):
        run = build().start()

        assert {str(call.quiz_id) for call in gateway.calls} == {str(run.quiz.id)}
        assert {call.lesson_id for call in gateway.calls} == {None}

    def test_the_total_marks_come_from_the_marks_table(self, build, questions):
        run = build(types=("mcq", "msq")).start()

        attempt = QuickQuizAttempt.objects.get(pk=run.attempt.pk)
        assert sum(q["marks"] for q in attempt.questions) == run.state()["blueprint"]["total_marks"]


class TestAQuizFromTwoLessons:
    @pytest.fixture
    def run(self, build, questions):
        return build(mode="existing_score", levels=("beginner", "expert"), count=10).start()

    def test_each_question_is_tagged_with_its_lesson_in_order(self, run):
        attempt = QuickQuizAttempt.objects.get(pk=run.attempt.pk)
        sources = QuickQuizSource.objects.filter(quiz=run.quiz)

        assert [q["source"] for q in attempt.questions] == [str(sources[0].lesson_id)] * 5 + [
            str(sources[1].lesson_id)
        ] * 5

    def test_each_batch_is_told_its_own_lessons_summary_and_not_the_others(self, run, gateway):
        first, second = (c.messages[1].content for c in gateway.called("test.generate"))
        a, b = sorted([first, second], key=lambda text: "SUMMARY-0" in text, reverse=True)

        assert "SUMMARY-0" in a and "SUMMARY-1" not in a
        assert "SUMMARY-1" in b and "SUMMARY-0" not in b

    def test_each_question_names_a_concept_of_its_own_lesson(self, run, gateway):
        attempt = QuickQuizAttempt.objects.get(pk=run.attempt.pk)

        plan_concepts = set(QuestionConcepts.outline(make_plan()))
        assert {q["concept"] for q in attempt.questions} <= plan_concepts

    def test_the_prompt_lists_the_concepts_under_the_lesson(self, run, gateway):
        users = [c.messages[1].content for c in gateway.called("test.generate")]

        assert all('Allowed concepts (copy one exactly into "concept"): ["Searching a list"' in u for u in users)

    def test_each_lessons_questions_are_at_that_lessons_level(self, run):
        attempt = QuickQuizAttempt.objects.get(pk=run.attempt.pk)

        beginner = [q["difficulty"] for q in attempt.questions[:5]]
        expert = [q["difficulty"] for q in attempt.questions[5:]]
        assert beginner.count("expert") == 0 and expert.count("easy") == 0 and expert.count("basic") == 0

    def test_the_quiz_shows_the_middle_level(self, run):
        assert QuickQuiz.objects.get(pk=run.quiz.pk).level == "proficient"  # between beginner and expert, rounded up


class TestALessonWithAConceptIndex:
    def test_the_summary_comes_from_the_index_and_the_questions_name_its_concepts(self, build, questions, gateway):
        run = build(mode="existing_score", levels=("proficient",), count=5)
        lesson = run.quiz.sources.get().lesson
        type(lesson).objects.filter(pk=lesson.pk).update(
            concept_index=[
                {
                    "concept": "Only in the index",
                    "page": "core",
                    "heading": "A heading",
                    "summary": "Told by the index.",
                }
            ]
        )

        run.start()

        user = gateway.called("test.generate")[0].messages[1].content
        assert "Told by the index." in user and "Searching a list" not in user
        attempt = QuickQuizAttempt.objects.get(pk=run.attempt.pk)
        assert {q["concept"] for q in attempt.questions} == {"Only in the index"}


class TestTheCalibrationWalk:
    @pytest.fixture
    def walking(self, build, questions, gateway):
        gateway.script("diagnostic.generate", pool_bundle())
        return build(mode="calibration").start()

    def test_the_graph_writes_a_pool_and_pauses_for_the_learner(self, walking):
        assert walking.nodes == ["load_quiz", "resolve_source", "generate_pool", "validate_pool", "publish_calibration"]
        assert "await_calibration" not in walking.nodes  # the node is waiting: it only finishes on the resume
        assert walking.interrupt == {"kind": "calibration", "quiz_id": str(walking.quiz.id)}

    def test_the_pool_is_kept_on_the_quiz_and_the_stage_waits(self, walking):
        quiz = QuickQuiz.objects.get(pk=walking.quiz.pk)

        assert quiz.stage == QuizStage.AWAITING_CALIBRATION
        assert len(quiz.calibration["pool"]) == 10 and quiz.calibration["walk"] == []

    def test_the_pool_asks_for_no_prerequisite_half(self, walking, gateway):
        (call,) = gateway.called("diagnostic.generate")

        assert (
            "PREREQUISITE QUIZ" not in call.messages[0].content
            and "exactly 10 multiple-choice" in call.messages[0].content
        )

    def test_the_attempt_waits_while_the_learner_walks(self, walking):
        assert QuickQuizAttempt.objects.get(pk=walking.attempt.pk).status == "generating"

    def test_after_the_walk_the_level_comes_from_the_ladder_and_the_quiz_is_built(self, walking, gateway):
        QuickQuiz.objects.filter(pk=walking.quiz.pk).update(
            calibration={**QuickQuiz.objects.get(pk=walking.quiz.pk).calibration,
                         "walk": [{"question_id": f"q{n}", "band": "x", "correct": True} for n in range(5)]},
        )  # fmt: skip

        walking.resume()

        assert walking.nodes[5:8] == ["await_calibration", "level_from_walk", "plan_quiz"]
        assert walking.nodes[-1] == "persist_attempt" and walking.interrupt is None
        quiz = QuickQuiz.objects.get(pk=walking.quiz.pk)
        assert (quiz.stage, quiz.level, quiz.assessment["source"]) == (QuizStage.READY, "expert", "calibration")
        assert QuickQuizAttempt.objects.get(pk=walking.attempt.pk).status == "in_progress"

    def test_the_pool_is_written_once_and_the_pause_is_not_a_second_one(self, walking, gateway):
        QuickQuiz.objects.filter(pk=walking.quiz.pk).update(
            calibration={"pool": [], "walk": [{"question_id": "q", "band": "x", "correct": False}] * 5},
        )

        walking.resume()

        assert len(gateway.called("diagnostic.generate")) == 1 and walking.nodes.count("await_calibration") == 1
        assert QuickQuiz.objects.get(pk=walking.quiz.pk).level == "beginner"

    def test_a_pool_that_keeps_failing_ends_the_run_before_any_question_is_written(self, build, questions, gateway):
        broken = DiagnosticBundle(diagnostic=make_questions()[:6], prerequisites=[], prerequisite_questions=[])
        gateway.respond("diagnostic.generate", broken.model_dump())
        run = build(mode="calibration")

        with pytest.raises(RunFailed, match="calibration questions"):
            run.start()

        assert gateway.called("test.generate") == []


class TestARetake:
    @pytest.fixture
    def retake(self, build, questions, make_attempt):
        run = build(
            stage=QuizStage.READY, assessment={"level": "proficient", "source": "self_rating", "level_scheme": 2}
        )
        QuickQuizAttempt.objects.filter(pk=run.attempt.pk).delete()
        first = [{**q, "id": f"t{n}"} for n, q in enumerate(self.earlier(), start=1)]
        make_attempt(run.quiz, status="graded", questions=first)
        run.attempt = make_attempt(run.quiz, status="generating", questions=[])
        questions.written = 100
        return run

    @staticmethod
    def earlier():
        return [make_question("mcq", n) for n in range(1, 11)]

    def test_it_does_not_ask_for_the_level_again(self, retake, gateway):
        retake.start()

        assert "level_from_rating" not in retake.nodes and "generate_pool" not in retake.nodes
        assert retake.nodes[:3] == ["load_quiz", "resolve_source", "plan_quiz"]
        assert gateway.called("diagnostic.generate") == []

    def test_every_question_the_quiz_has_asked_is_given_as_one_not_to_repeat(self, retake, gateway):
        retake.start()

        prompt = gateway.called("test.generate")[0].messages[1].content
        for question in self.earlier():
            assert question["question"] in prompt

    def test_the_new_attempt_starts_with_new_questions_at_the_known_level(self, retake):
        retake.start()

        new = QuickQuizAttempt.objects.get(pk=retake.attempt.pk)
        old = {q["question"] for q in self.earlier()}
        assert (
            new.status == "in_progress" and new.attempt_no == 2 and not ({q["question"] for q in new.questions} & old)
        )
        assert retake.state()["quiz"]["level"] == "proficient"

    def test_the_quiz_stays_ready_throughout(self, retake):
        retake.start()

        assert QuickQuiz.objects.get(pk=retake.quiz.pk).stage == QuizStage.READY


class TestAQuizThatIsGone:
    def test_a_stopped_or_deleted_quiz_has_no_waiting_attempt(self, build, questions):
        run = build()
        QuickQuizAttempt.objects.filter(pk=run.attempt.pk).delete()

        with pytest.raises(RunFailed, match="cancelled"):
            run.start()

    def test_a_quiz_whose_lesson_was_deleted_cannot_be_taken_again(self, build, questions):
        run = build(mode="existing_score", levels=("beginner",))
        QuickQuizSource.objects.get(quiz=run.quiz).lesson.delete()

        with pytest.raises(RunFailed, match="deleted"):
            run.start()


class TestAQuizThatCannotBeFilled:
    def test_a_quiz_with_no_usable_question_fails(self, build, gateway):
        gateway.respond("test.generate", lambda messages: QuestionBatch(questions=[]))
        run = build()

        with pytest.raises(RunFailed):
            run.start()

        assert QuickQuizAttempt.objects.get(pk=run.attempt.pk).status == "generating"
