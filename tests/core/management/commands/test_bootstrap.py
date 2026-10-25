"""Unit under test: `manage.py bootstrap`, which runs on every backend start.

Why: it prepares the database before the API serves requests. If it skipped the migrations, or the checkpoint tables,
the first lesson would fail with a missing-table error that looks like an application bug.

Use cases:
- on the local database it migrates, then creates the checkpoint tables
- with Supabase it syncs local rows up (which migrates both), then creates the checkpoint tables
- with Supabase but syncing switched off it migrates only
"""

import pytest
from django.core.management import call_command

from core.management.commands import bootstrap


@pytest.fixture
def calls(monkeypatch):
    seen = []
    monkeypatch.setattr(bootstrap, "call_command", lambda name, **kwargs: seen.append(name))
    return seen


def test_local_database_migrates_then_creates_the_checkpoint_tables(calls, settings):
    settings.USING_SUPABASE = False

    call_command("bootstrap")

    assert calls == ["migrate", "setup_checkpointer"]


def test_supabase_syncs_local_rows_then_creates_the_checkpoint_tables(calls, settings):
    settings.USING_SUPABASE, settings.SYNC_LOCAL_TO_SUPABASE = True, True

    call_command("bootstrap")

    assert calls == ["sync_to_supabase", "setup_checkpointer"]


def test_supabase_without_syncing_only_migrates(calls, settings):
    settings.USING_SUPABASE, settings.SYNC_LOCAL_TO_SUPABASE = True, False

    call_command("bootstrap")

    assert calls == ["migrate", "setup_checkpointer"]
