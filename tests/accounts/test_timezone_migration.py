"""Unit under test: accounts migration 0004 (`profile_timezone`), which adds `Profile.timezone` and
`Profile.timezone_changed_at`.

Why: every existing learner gets a profile row with these columns. Giving them a made-up zone or a "changed" date would
start a 30-day lock they never asked for, or put their streak on the wrong day. They must start with no zone, so that
Asia/Kolkata is used until they or their browser say otherwise.

Use cases:
- every profile that existed before the migration has a blank zone and no change date
- undoing the migration drops the two columns and keeps the rest of the profile
"""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

# One-time data migration: skipped by the everyday local run; CI and `make check-full` run it (docs/process/testing.md).
pytestmark = pytest.mark.migration

BEFORE = [("accounts", "0003_terms_consent")]


def latest():
    return list(MigrationExecutor(connection).loader.graph.leaf_nodes("accounts"))


def migrate(targets):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)
    return MigrationExecutor(connection).loader.project_state(targets).apps


@pytest.mark.django_db(transaction=True)
def test_existing_profiles_start_with_no_zone_and_no_lock_and_the_migration_can_be_undone():
    old = migrate(BEFORE)
    User, Profile = old.get_model("accounts", "User"), old.get_model("accounts", "Profile")
    user = User.objects.create(email="old@example.com", name="Old", password="x")
    Profile.objects.create(user=user, notes="keep me")

    try:
        new = migrate(latest())
        profile = new.get_model("accounts", "Profile").objects.get(user__email="old@example.com")
        assert profile.timezone == "" and profile.timezone_changed_at is None and profile.notes == "keep me"

        back = migrate(BEFORE)
        kept = back.get_model("accounts", "Profile").objects.get(user__email="old@example.com")
        assert kept.notes == "keep me" and not hasattr(kept, "timezone")
    finally:
        migrate(latest())
