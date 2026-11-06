"""Unit under test: credits migrations 0001 (`ledger`, the tables) and 0002 (`ledger_append_only`, the trigger).

Why: the append-only rule is only as good as the database it runs in. The trigger is part of the schema, so it must
exist
after a normal migrate, refuse an UPDATE and a DELETE from anyone (the model guard is not the only door), and leave and
return cleanly when a migration is undone. Adding the tables must also leave existing learners alone.

Use cases:
- after migrating, the five tables exist and the ledger table has the append-only trigger
- raw SQL that updates or deletes a ledger row is refused by the database, while inserting still works
- the other credits tables can be updated (buckets and holds change as credits move)
- the ledger needs only the user table, so undoing the newer accounts migrations (as the accounts migration tests do)
  leaves the credits tables and the trigger in place
- no credits migration needs more of accounts than its first, whatever migrations have been added to accounts
- undoing 0002 removes the trigger and migrating forward puts it back; undoing 0001 drops the tables and keeps the
  learners
"""

import pytest
from django.db import DatabaseError, connection, transaction
from django.db.migrations.executor import MigrationExecutor

BEFORE_TRIGGER = [("credits", "0001_ledger")]
ZERO = [("credits", None)]
TABLES = [
    "credits_wallet",
    "credits_creditbucket",
    "credits_credithold",
    "credits_credittransaction",
    "credits_creditsettings",
]


def latest():
    """Where everything goes back to: every app's newest migration. `payments` depends on `credits` and is undone with
    it, and going forward again to only the newest of `credits` would leave its tables missing for later tests."""
    return list(MigrationExecutor(connection).loader.graph.leaf_nodes())


def migrate(targets):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)


def tables():
    return set(connection.introspection.table_names())


def has_trigger() -> bool:
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_trigger WHERE tgname = 'credits_transaction_append_only'")
        return cursor.fetchone() is not None


def insert_row(user_id, key="k"):
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO credits_credittransaction (user_id, type, amount, balance_after, action, subject_kind, "
            "bucket_allocations, idempotency_key, meta, created_at) "
            "VALUES (%s, 'grant', 1, 1, '', '', '[]', %s, '{}', now())",
            [user_id, key],
        )


@pytest.mark.django_db
def test_the_tables_and_the_trigger_exist_after_migrating():
    assert set(TABLES) <= tables() and has_trigger()


@pytest.mark.django_db
def test_the_database_refuses_to_update_or_delete_a_ledger_row_but_accepts_a_new_one(user):
    insert_row(user.pk, "first")
    insert_row(user.pk, "second")

    with pytest.raises(DatabaseError, match="append-only"), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("UPDATE credits_credittransaction SET amount = 999")
    with pytest.raises(DatabaseError, match="append-only"), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("DELETE FROM credits_credittransaction WHERE idempotency_key = 'first'")

    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*), sum(amount) FROM credits_credittransaction")
        assert cursor.fetchone() == (2, 2)


@pytest.mark.django_db
def test_buckets_and_holds_can_be_updated(user):
    from datetime import UTC, datetime

    from credits.models import CreditBucket

    made = CreditBucket.objects.create(
        user=user, source="daily", amount_granted=5, amount_remaining=5, created_at=datetime(2026, 1, 1, tzinfo=UTC)
    )

    CreditBucket.objects.filter(pk=made.pk).update(amount_remaining=1)

    assert CreditBucket.objects.get(pk=made.pk).amount_remaining == 1


@pytest.mark.django_db(transaction=True)
def test_undoing_the_trigger_migration_removes_it_and_going_forward_restores_it(user):
    try:
        migrate(BEFORE_TRIGGER)
        assert not has_trigger() and "credits_credittransaction" in tables()

        migrate(latest())
        assert has_trigger()
    finally:
        migrate(latest())


@pytest.mark.django_db(transaction=True)
def test_undoing_the_first_migration_drops_the_tables_and_keeps_the_learners(user):
    try:
        migrate(ZERO)
        assert not set(TABLES) & tables() and not has_trigger()
        from accounts.models import User

        assert User.objects.filter(pk=user.pk).exists()
    finally:
        migrate(latest())
        assert set(TABLES) <= tables() and has_trigger()


@pytest.mark.django_db(transaction=True)
def test_undoing_the_newer_accounts_migrations_leaves_the_ledger_alone(user):
    parents = MigrationExecutor(connection).loader.graph.node_map[("credits", "0001_ledger")].parents
    assert {p.key for p in parents if p.key[0] == "accounts"} == {("accounts", "0001_initial")}
    try:
        migrate([("accounts", "0001_initial")])

        assert set(TABLES) <= tables() and has_trigger()
    finally:
        migrate(list(MigrationExecutor(connection).loader.graph.leaf_nodes()))


@pytest.mark.django_db
def test_no_credits_migration_needs_more_of_accounts_than_its_first(user):
    """Else undoing a newer accounts migration would undo that credits migration too (the accounts tests do)."""
    graph = MigrationExecutor(connection).loader.graph
    needed = {
        parent.key
        for key, node in graph.node_map.items()
        if key[0] == "credits"
        for parent in node.parents
        if parent.key[0] == "accounts"
    }

    assert needed == {("accounts", "0001_initial")}
