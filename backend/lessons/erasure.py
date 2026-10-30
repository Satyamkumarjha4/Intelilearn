"""What deleting a lesson must remove besides the rows Django cascades: its LangGraph checkpoints and its model calls.

Both can hold the learner's words, and neither is reached by the cascade: checkpoints are not Django models, and
`ModelCall` keeps a plain `lesson_id` so the usage log outlives nothing it should not (see data-model.md).
"""

import logging
from typing import Protocol

import psycopg

from llm_registry.models import ModelCall

from .checkpoints import CheckpointerFactory
from .models import GraphRun, Lesson
from .runner import FlowRunner

logger = logging.getLogger(__name__)


class ThreadStore(Protocol):
    def delete(self, thread_ids: list[str]) -> None: ...


class CheckpointThreads:
    """Deletes whole LangGraph threads from the Postgres checkpoint tables."""

    def __init__(self, checkpointers: CheckpointerFactory | None = None):
        self.checkpointers = checkpointers or CheckpointerFactory()

    def delete(self, thread_ids: list[str]) -> None:
        try:
            with self.checkpointers.saver() as saver:
                for thread_id in thread_ids:
                    saver.delete_thread(thread_id)
        except psycopg.errors.UndefinedTable:
            logger.info("No checkpoint tables, so no threads to delete")  # `setup_checkpointer` has never run here


class LessonErasure:
    def __init__(self, threads: ThreadStore | None = None):
        self.threads = threads or CheckpointThreads()

    def erase(self, lesson: Lesson) -> None:
        """Call before the lesson row goes: it needs the lesson's runs to name their threads."""
        runs = GraphRun.objects.for_subject(lesson)
        self.threads.delete(sorted({str(lesson.id), *(FlowRunner.thread_id(run) for run in runs)}))
        ModelCall.objects.filter(lesson_id=lesson.id).delete()
