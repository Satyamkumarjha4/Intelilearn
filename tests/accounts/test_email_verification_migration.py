"""Unit under test: accounts migration 0006 (`user_email_verification`), which adds `email_verified_at`,
`email_verification_source` and the unique `email_canonical` to `User`.

Why: from phase 11 the signup credits go only to a verified email, one account per inbox. The accounts that exist
when the
migration runs must keep working (they are marked verified, with a source that says nobody proved the inbox), every
one must
get a canonical email, two that collapse to the same inbox must not stop the migration, and undoing it must not touch a
person.

Use cases:
- every existing account is marked verified at the day it joined, with the source `legacy`; an erased account is not
- every account gets its canonical email (aliases of Gmail collapse, other dots stay)
- when two existing accounts collapse to one inbox, the earlier keeps the canonical address and the later gets a marked,
  unique one; the migration does not fail, and a third alias is marked too
- the canonical column is unique after the migration
- undoing the migration drops the columns and keeps the users
"""

from datetime import UTC, datetime

import pytest
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor

# One-time data migration: skipped by the everyday local run; CI and `make check-full` run it (docs/process/testing.md).
pytestmark = pytest.mark.migration

BEFORE = [("accounts", "0005_user_deleted_at")]


def latest():
    return list(MigrationExecutor(connection).loader.graph.leaf_nodes("accounts"))


def migrate(targets):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)
    return MigrationExecutor(connection).loader.project_state(targets).apps


def joined(day):
    return datetime(2026, 1, day, 9, 0, tzinfo=UTC)


@pytest.mark.django_db(transaction=True)
def test_existing_accounts_are_marked_legacy_and_get_their_canonical_email():
    old = migrate(BEFORE)
    User = old.get_model("accounts", "User")
    User.objects.create(email="ada@example.com", name="Ada", password="x", date_joined=joined(1))
    User.objects.create(email="grace.h+old@gmail.com", name="Grace", password="x", date_joined=joined(2))
    User.objects.create(email="a.b@yahoo.com", name="Yahoo", password="x", date_joined=joined(3))
    User.objects.create(
        email="deleted-1@erased.invalid", name="", password="x", date_joined=joined(4), deleted_at=joined(5)
    )

    try:
        new = migrate(latest())
        users = {u.email: u for u in new.get_model("accounts", "User").objects.all()}

        assert users["ada@example.com"].email_verified_at == joined(1)
        assert users["ada@example.com"].email_verification_source == "legacy"
        assert users["ada@example.com"].email_canonical == "ada@example.com"
        assert users["grace.h+old@gmail.com"].email_canonical == "graceh@gmail.com"
        assert users["a.b@yahoo.com"].email_canonical == "a.b@yahoo.com"
        erased = users["deleted-1@erased.invalid"]
        assert erased.email_verified_at is None and erased.email_verification_source == ""
        assert erased.email_canonical == "deleted-1@erased.invalid"
    finally:
        migrate(latest())


@pytest.mark.django_db(transaction=True)
def test_two_accounts_that_collapse_to_one_inbox_do_not_stop_the_migration():
    old = migrate(BEFORE)
    User = old.get_model("accounts", "User")
    first = User.objects.create(email="a.b@gmail.com", name="First", password="x", date_joined=joined(1))
    second = User.objects.create(email="ab@gmail.com", name="Second", password="x", date_joined=joined(2))
    third = User.objects.create(email="a.b+x@googlemail.com", name="Third", password="x", date_joined=joined(3))

    try:
        new = migrate(latest())
        User = new.get_model("accounts", "User")

        assert User.objects.get(pk=first.pk).email_canonical == "ab@gmail.com"
        assert User.objects.get(pk=second.pk).email_canonical == f"dup:{second.pk}:ab@gmail.com"
        assert User.objects.get(pk=third.pk).email_canonical == f"dup:{third.pk}:a.b+x@googlemail.com"
        assert len({u.email_canonical for u in User.objects.all()}) == 3
        assert all(u.email_verification_source == "legacy" for u in User.objects.all())  # nobody lost their account
    finally:
        migrate(latest())


@pytest.mark.django_db(transaction=True)
def test_the_canonical_email_is_unique_after_the_migration():
    migrate(latest())
    from accounts.models import User

    User.objects.create_user("one@example.com", password="x", name="One")

    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.create_user("one+again@example.com", password="x", name="Two")


@pytest.mark.django_db(transaction=True)
def test_undoing_the_migration_drops_the_columns_and_keeps_the_users():
    old = migrate(BEFORE)
    old.get_model("accounts", "User").objects.create(email="old@example.com", name="Old", password="x")

    try:
        migrate(latest())
        back = migrate(BEFORE)
        kept = back.get_model("accounts", "User").objects.get(email="old@example.com")

        assert kept.name == "Old"
        assert not hasattr(kept, "email_canonical") and not hasattr(kept, "email_verified_at")
    finally:
        migrate(latest())
