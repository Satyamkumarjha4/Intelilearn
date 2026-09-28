import pytest
from django.contrib.auth.models import Group, User

from core.sync import sync_databases

BOTH = pytest.mark.django_db(databases=["default", "local"])


@BOTH
def test_copies_rows_missing_on_target():
    user = User.objects.db_manager("local").create_user("ada", password="x")

    report = sync_databases(source="local", target="default")

    assert User.objects.using("default").filter(pk=user.pk, username="ada").exists()
    assert report.inserted == 1


@BOTH
def test_second_run_copies_nothing():
    User.objects.db_manager("local").create_user("ada", password="x")
    sync_databases(source="local", target="default")

    report = sync_databases(source="local", target="default")

    assert report.inserted == 0
    assert User.objects.using("default").count() == 1


@BOTH
def test_never_overwrites_existing_target_rows():
    local = User.objects.db_manager("local").create_user("ada", password="x", first_name="Local")
    User.objects.db_manager("default").create_user("ada", password="x", first_name="Supabase", id=local.pk)

    sync_databases(source="local", target="default")

    assert User.objects.using("default").get(pk=local.pk).first_name == "Supabase"


@BOTH
def test_unique_clash_is_reported_not_raised():
    User.objects.db_manager("default").create_user("ada", password="x")
    User.objects.db_manager("local").create_user("placeholder", password="x")
    clash = User.objects.db_manager("local").create_user("ada", password="x")  # same username, other pk

    report = sync_databases(source="local", target="default")

    assert report.conflicts == 1
    assert not User.objects.using("default").filter(pk=clash.pk).exists()


@BOTH
def test_many_to_many_links_follow_the_object():
    group = Group.objects.using("local").create(name="learners")
    user = User.objects.db_manager("local").create_user("ada", password="x")
    user.groups.add(group)

    sync_databases(source="local", target="default")

    copied = User.objects.using("default").get(pk=user.pk)
    assert list(copied.groups.values_list("name", flat=True)) == ["learners"]


@BOTH
def test_sequences_are_reset_after_copy():
    for i in range(3):
        User.objects.db_manager("local").create_user(f"user{i}", password="x")
    sync_databases(source="local", target="default")

    fresh = User.objects.db_manager("default").create_user("new", password="x")

    assert fresh.pk > User.objects.using("local").order_by("-pk").first().pk
