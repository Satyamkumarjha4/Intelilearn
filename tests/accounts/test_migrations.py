"""Unit under test: accounts migrations 0002 (`profile_choices_and_note_limit`), which puts choices on
`Profile.preferred_language` and a length limit on `Profile.notes`, and 0003 (`terms_consent`), which adds when and
to which version of the terms a user agreed.

Why: the constraints are only safe to add if the rows already stored obey them. A language the profile no longer lists
would make every later save of that learner fail validation, and an over-long note the same.

Use cases:
- a stored language that is one of the five stays as it is
- any other stored language (a name, a regional code, blank) becomes English
- a note within the limit is untouched, a longer one is cut to the limit
- the migration can be undone without touching the data
- 0003 leaves every existing user with no recorded consent (never a made-up date or version), and undoing it keeps the
  rest of the user
"""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

BEFORE = [("accounts", "0001_initial")]
BEFORE_CONSENT = [("accounts", "0002_profile_choices_and_note_limit")]
CONSENT = [("accounts", "0003_terms_consent")]
AFTER = [("accounts", "0002_profile_choices_and_note_limit")]


def latest():
    """The newest accounts migration: where the test database must be left, whatever has been added since 0002."""
    return list(MigrationExecutor(connection).loader.graph.leaf_nodes("accounts"))


def migrate(targets):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)
    return MigrationExecutor(connection).loader.project_state(targets).apps


@pytest.mark.django_db(transaction=True)
def test_existing_rows_are_made_to_fit_the_new_limits():
    old = migrate(BEFORE)
    User, Profile = old.get_model("accounts", "User"), old.get_model("accounts", "Profile")
    stored = {"hi": "hi", "English": "en", "fr-FR": "en", "": "en", "de": "de"}
    for n, language in enumerate(stored):
        user = User.objects.create(email=f"u{n}@example.com", name="U", password="x")
        Profile.objects.create(user=user, preferred_language=language, notes="n" * (2500 if language == "hi" else 5))

    try:
        new = migrate(AFTER)
        Profile = new.get_model("accounts", "Profile")
        rows = {p.user.email: p for p in Profile.objects.select_related("user")}

        assert [rows[f"u{n}@example.com"].preferred_language for n in range(len(stored))] == list(stored.values())
        assert len(rows["u0@example.com"].notes) == 2000  # was 2500
        assert rows["u1@example.com"].notes == "nnnnn"
    finally:
        migrate(latest())  # leave the test database at the latest state for the tests that follow


@pytest.mark.django_db(transaction=True)
def test_the_migration_can_be_undone_without_touching_data():
    new = migrate(AFTER)
    User, Profile = new.get_model("accounts", "User"), new.get_model("accounts", "Profile")
    Profile.objects.create(user=User.objects.create(email="a@example.com", name="A", password="x"), notes="keep me")

    try:
        old = migrate(BEFORE)

        assert old.get_model("accounts", "Profile").objects.get().notes == "keep me"
    finally:
        migrate(latest())


@pytest.mark.django_db(transaction=True)
def test_users_from_before_the_terms_have_no_consent_recorded_and_the_migration_can_be_undone():
    old = migrate(BEFORE_CONSENT)
    User = old.get_model("accounts", "User")
    User.objects.create(email="early@example.com", name="Early", password="x")

    try:
        new = migrate(CONSENT)
        early = new.get_model("accounts", "User").objects.get(email="early@example.com")

        assert (early.terms_accepted_at, early.terms_version) == (None, "")  # they never agreed: the data says so

        back = migrate(BEFORE_CONSENT)
        assert back.get_model("accounts", "User").objects.get(email="early@example.com").name == "Early"
    finally:
        migrate(latest())
