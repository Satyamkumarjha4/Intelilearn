"""Unit under test: `manage.py setup_checkpointer`, which creates the LangGraph checkpoint tables.

Why: without those tables a paused lesson cannot be saved, so no quiz could ever be resumed. The command must work on
a fresh database and on one that already has the tables (it runs on every backend start).

Use cases:
- creates the checkpoint tables and says so
- can run again on a database that already has them
"""

from io import StringIO

import pytest
from django.core.management import call_command
from django.db import connection

pytestmark = pytest.mark.django_db


def tables_exist() -> bool:
    with connection.cursor() as cursor:
        cursor.execute("select to_regclass('public.checkpoints') is not null")
        return cursor.fetchone()[0]


def test_creates_the_checkpoint_tables():
    out = StringIO()

    call_command("setup_checkpointer", stdout=out)

    assert tables_exist() and "Checkpoint tables are ready." in out.getvalue()


def test_can_run_again_on_a_database_that_has_them():
    call_command("setup_checkpointer", stdout=StringIO())

    call_command("setup_checkpointer", stdout=StringIO())

    assert tables_exist()
