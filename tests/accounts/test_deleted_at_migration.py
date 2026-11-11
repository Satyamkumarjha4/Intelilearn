"""Unit under test: accounts migration 0005 (`user_deleted_at`), which adds `User.deleted_at`.

Why: an erased account is told apart from a live one by this column, so every existing account must start as not
erased, and
undoing the migration must not touch the account.

Use cases:
- every user that existed before the migration has no deletion date
- undoing the migration drops the column and keeps the user
"""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

# One-time data migration: skipped by the everyday local run; CI and `make check-full` run it (docs/process/testing.md).
pytestmark = pytest.mark.migration

BEFORE = [("accounts", "0004_profile_timezone")]


def latest():
    return list(MigrationExecutor(connection).loader.graph.leaf_nodes("accounts"))


def migrate(targets):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)
    return MigrationExecutor(connection).loader.project_state(targets).apps


@pytest.mark.django_db(transaction=True)
def test_existing_users_are_not_erased_and_the_migration_can_be_undone():
    old = migrate(BEFORE)
    old.get_model("accounts", "User").objects.create(email="old@example.com", name="Old", password="x")

    try:
        new = migrate(latest())
        assert new.get_model("accounts", "User").objects.get(email="old@example.com").deleted_at is None

        back = migrate(BEFORE)
        kept = back.get_model("accounts", "User").objects.get(email="old@example.com")
        assert kept.name == "Old" and not hasattr(kept, "deleted_at")
    finally:
        migrate(latest())
