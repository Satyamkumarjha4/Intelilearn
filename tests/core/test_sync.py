"""Unit under test: `core.sync.DatabaseSyncer`, the insert-only copy of local rows to Supabase on every backend start.

Why: it writes to the shared database unattended. Overwriting, duplicating or mis-ordering rows would corrupt real
user data, and a sequence left behind would make the next insert on Supabase fail.

Use cases:
- copies rows that the target is missing
- copies a user's profile together with the user (foreign-key order)
- is a no-op on the second run
- never overwrites rows that already exist on the target (insert-only)
- reports a unique-constraint clash instead of raising, so start-up continues
- carries many-to-many links along with their object
- resets primary-key sequences so new rows on the target don't collide
"""

import pytest
from django.contrib.auth.models import Group

from accounts.models import Profile, User
from core.sync import DatabaseSyncer

BOTH = pytest.mark.django_db(databases=["default", "local"])


def local_user(email, **extra):
    return User.objects.db_manager("local").create_user(email, password="x", name=email.split("@")[0], **extra)


@BOTH
def test_copies_rows_missing_on_target():
    user = local_user("ada@example.com")

    report = DatabaseSyncer(source="local", target="default").sync()

    assert User.objects.using("default").filter(pk=user.pk, email="ada@example.com").exists()
    assert report.models["accounts.User"].inserted == 1


@BOTH
def test_profile_travels_with_its_user():
    user = local_user("ada@example.com")
    Profile.objects.using("local").filter(user=user).update(goal="exam_prep")

    DatabaseSyncer(source="local", target="default").sync()

    assert Profile.objects.using("default").get(user_id=user.pk).goal == "exam_prep"


@BOTH
def test_second_run_copies_nothing():
    local_user("ada@example.com")
    DatabaseSyncer(source="local", target="default").sync()

    report = DatabaseSyncer(source="local", target="default").sync()

    assert report.inserted == 0
    assert User.objects.using("default").count() == 1


@BOTH
def test_never_overwrites_existing_target_rows():
    local = local_user("ada@example.com")
    User.objects.using("local").filter(pk=local.pk).update(name="Local")
    User.objects.db_manager("default").create_user("ada@example.com", password="x", name="Supabase", id=local.pk)

    DatabaseSyncer(source="local", target="default").sync()

    assert User.objects.using("default").get(pk=local.pk).name == "Supabase"


@BOTH
def test_unique_clash_is_reported_not_raised():
    User.objects.db_manager("default").create_user("ada@example.com", password="x", name="Ada")
    clash = local_user("ada@example.com")  # same email, different id

    report = DatabaseSyncer(source="local", target="default").sync()

    assert report.models["accounts.User"].conflicts == 1
    assert not User.objects.using("default").filter(pk=clash.pk).exists()


@BOTH
def test_many_to_many_links_follow_the_object():
    group = Group.objects.using("local").create(name="learners")
    user = local_user("ada@example.com")
    user.groups.add(group)

    DatabaseSyncer(source="local", target="default").sync()

    copied = User.objects.using("default").get(pk=user.pk)
    assert list(copied.groups.values_list("name", flat=True)) == ["learners"]


@BOTH
def test_sequences_are_reset_after_copy():
    for i in range(3):
        Group.objects.using("local").create(name=f"group{i}")
    DatabaseSyncer(source="local", target="default").sync()

    fresh = Group.objects.using("default").create(name="new")

    assert fresh.pk > Group.objects.using("local").order_by("-pk").first().pk
