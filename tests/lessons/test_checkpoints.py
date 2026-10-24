"""Unit under test: `lessons.checkpoints.CheckpointerFactory`, which gives the graph a durable Postgres checkpointer.

Why: a lesson can wait at a quiz for days. If its checkpoint lived in memory, restarting the worker would lose the
lesson. The factory must connect to the *active* database (the docker Postgres, or Supabase), including in tests where
Django uses a separate test database.

Use cases:
- builds the connection string from the active Django database settings
- carries SSL options through (Supabase needs sslmode=require)
- setup creates the checkpoint tables, and can be repeated
- a saver round-trips a checkpoint written by another saver (durability across processes)
"""

import uuid

import pytest
from django.db import connection
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from lessons.checkpoints import CheckpointerFactory


def test_builds_the_connection_string_from_the_active_database():
    settings_dict = {"NAME": "lc", "USER": "u", "PASSWORD": "p@ss", "HOST": "db", "PORT": "5432", "OPTIONS": {}}

    info = CheckpointerFactory(settings_dict).conninfo()

    assert info == "postgresql://u:p%40ss@db:5432/lc"


def test_carries_ssl_options_through():
    settings_dict = {"NAME": "lc", "USER": "u", "PASSWORD": "p", "HOST": "h", "PORT": "6543",
                     "OPTIONS": {"sslmode": "require"}}  # fmt: skip

    assert CheckpointerFactory(settings_dict).conninfo().endswith("/lc?sslmode=require")


def test_defaults_the_port_when_the_settings_have_none():
    settings_dict = {"NAME": "lc", "USER": "u", "PASSWORD": "p", "HOST": "h", "PORT": "", "OPTIONS": {}}

    assert ":5432/" in CheckpointerFactory(settings_dict).conninfo()


class Counter(TypedDict):
    n: int


def counter_graph(checkpointer):
    graph = StateGraph(Counter)
    graph.add_node("inc", lambda state: {"n": state.get("n", 0) + 1})
    graph.add_edge(START, "inc")
    graph.add_edge("inc", END)
    return graph.compile(checkpointer=checkpointer)


@pytest.mark.django_db
def test_setup_creates_the_tables_and_can_be_repeated(django_db_blocker):
    factory = CheckpointerFactory(connection.settings_dict)

    factory.setup()
    factory.setup()

    with connection.cursor() as cursor:
        cursor.execute("select to_regclass('public.checkpoints') is not null")
        assert cursor.fetchone()[0] is True


@pytest.mark.django_db
def test_a_second_saver_reads_what_the_first_one_wrote():
    factory = CheckpointerFactory(connection.settings_dict)
    factory.setup()
    config = {"configurable": {"thread_id": f"test-{uuid.uuid4()}"}}

    with factory.saver() as first:
        counter_graph(first).invoke({"n": 41}, config)
    with factory.saver() as second:  # a different connection, as after a worker restart
        state = counter_graph(second).get_state(config)

    assert state.values == {"n": 42}
