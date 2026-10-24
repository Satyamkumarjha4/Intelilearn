"""Drives the compiled lesson-flow graph the way `FlowRunner` does, for graph tests: stream one segment, remember the
nodes that ran and the interrupt it stopped at, answer a quiz or resume with a value, and read the thread's state."""

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from graph.builders import FlowGraphBuilder
from graph.grading import QuizGrader
from lessons.models import Lesson, Quiz, QuizAttempt


class GraphDriver:
    """Drives the compiled graph like `FlowRunner`: stream a segment, remember the nodes that ran, then resume."""

    def __init__(self, lesson, ctx, lesson_state, segments=None):
        self.lesson, self.ctx = lesson, ctx
        self.graph = FlowGraphBuilder(segments=segments).build(InMemorySaver())
        self.config = {"configurable": {"thread_id": str(lesson.id)}}
        Lesson.objects.filter(pk=lesson.pk).update(
            config_snapshot=lesson_state["snapshot"], settings_snapshot=lesson_state["settings"]
        )
        self.nodes: list[str] = []
        self.interrupt = None

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
        return self.stream({"lesson_id": str(self.lesson.id)})

    def answer(self, kind: str, right: int):
        quiz = Quiz.objects.get(lesson=self.lesson, kind=kind)
        answers = {q["id"]: q["correct_index"] if n < right else (q["correct_index"] + 1) % 4
                   for n, q in enumerate(quiz.questions)}  # fmt: skip
        result = QuizGrader().grade(quiz.questions, answers).as_dict()
        attempt = QuizAttempt.objects.create(quiz=quiz, answers=answers, result=result)
        return self.stream(Command(resume=str(attempt.id)))

    def state(self):
        return self.graph.get_state(self.config).values
