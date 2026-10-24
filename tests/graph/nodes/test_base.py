"""Unit under test: `graph.nodes.base.Node`, the callable every graph node is built on.

Why: LangGraph runs nodes on pool threads, and Django gives each thread its own database connection. If a node left
its connection open, every lesson run would leak connections until Postgres refused new ones.

Use cases:
- a node run on a worker thread closes that thread's database connection when it ends, even if it raised
- a node run on the main thread (tests, management commands) leaves the connection alone
"""

import threading

import pytest
from django.db import connection

from graph.nodes.base import Node
from lessons.models import Lesson

pytestmark = pytest.mark.django_db(transaction=True)


class TouchesTheDatabase(Node):
    name = "touch"

    def __init__(self, fail: bool = False):
        self.fail = fail

    def run(self, state, ctx):
        Lesson.objects.count()
        if self.fail:
            raise RuntimeError("boom")
        return {}


def run_on_thread(node, runtime) -> dict:
    """→ whether the thread's connection was open before and after the node, and what the node raised."""
    seen: dict = {}

    def target():
        try:
            node({"lesson_id": "x"}, runtime)
        except RuntimeError as exc:
            seen["error"] = str(exc)
        seen["open_after"] = connection.connection is not None

    thread = threading.Thread(target=target)
    thread.start()
    thread.join()
    return seen


def test_a_node_on_a_worker_thread_closes_its_connection(runtime):
    assert run_on_thread(TouchesTheDatabase(), runtime) == {"open_after": False}


def test_a_failing_node_on_a_worker_thread_still_closes_its_connection(runtime):
    assert run_on_thread(TouchesTheDatabase(fail=True), runtime) == {"error": "boom", "open_after": False}


def test_a_node_on_the_main_thread_leaves_the_connection_open(runtime):
    TouchesTheDatabase()({"lesson_id": "x"}, runtime)

    assert connection.connection is not None
