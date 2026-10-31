"""What deleting a quiz must remove besides the rows Django cascades: its LangGraph checkpoints and its model calls.

A quiz's checkpoint holds the calibration pool with its answer keys, and the questions it wrote; its model calls hold
the learner's words. Neither is reached by the cascade. (The calibration column goes with the row.)
"""

from lessons.erasure import CheckpointThreads, ThreadStore
from lessons.models import GraphRun
from lessons.runner import FlowRunner
from llm_registry.models import ModelCall

from .models import QuickQuiz


class QuizErasure:
    def __init__(self, threads: ThreadStore | None = None):
        self.threads = threads or CheckpointThreads()

    def erase(self, quiz: QuickQuiz) -> None:
        """Call before the quiz row goes: it needs the quiz's runs to name their threads."""
        runs = GraphRun.objects.for_subject(quiz)
        self.threads.delete(sorted({str(quiz.id), *(FlowRunner.thread_id(run) for run in runs)}))
        ModelCall.objects.filter(quiz_id=quiz.id).delete()
