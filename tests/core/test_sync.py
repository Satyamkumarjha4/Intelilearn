import pytest
from django.contrib.auth.models import Group

from accounts.models import Profile, User
from core.sync import sync_databases

BOTH = pytest.mark.django_db(databases=["default", "local"])


def local_user(email, **extra):
    return User.objects.db_manager("local").create_user(email, password="x", name=email.split("@")[0], **extra)


@BOTH
def test_copies_rows_missing_on_target():
    user = local_user("ada@example.com")

    report = sync_databases(source="local", target="default")

    assert User.objects.using("default").filter(pk=user.pk, email="ada@example.com").exists()
    assert report.models["accounts.User"].inserted == 1


@BOTH
def test_profile_travels_with_its_user():
    user = local_user("ada@example.com")
    Profile.objects.using("local").filter(user=user).update(goal="exam_prep")

    sync_databases(source="local", target="default")

    assert Profile.objects.using("default").get(user_id=user.pk).goal == "exam_prep"


@BOTH
def test_second_run_copies_nothing():
    local_user("ada@example.com")
    sync_databases(source="local", target="default")

    report = sync_databases(source="local", target="default")

    assert report.inserted == 0
    assert User.objects.using("default").count() == 1


@BOTH
def test_never_overwrites_existing_target_rows():
    local = local_user("ada@example.com")
    User.objects.using("local").filter(pk=local.pk).update(name="Local")
    User.objects.db_manager("default").create_user("ada@example.com", password="x", name="Supabase", id=local.pk)

    sync_databases(source="local", target="default")

    assert User.objects.using("default").get(pk=local.pk).name == "Supabase"


@BOTH
def test_unique_clash_is_reported_not_raised():
    User.objects.db_manager("default").create_user("ada@example.com", password="x", name="Ada")
    clash = local_user("ada@example.com")  # same email, different id

    report = sync_databases(source="local", target="default")

    assert report.models["accounts.User"].conflicts == 1
    assert not User.objects.using("default").filter(pk=clash.pk).exists()


@BOTH
def test_many_to_many_links_follow_the_object():
    group = Group.objects.using("local").create(name="learners")
    user = local_user("ada@example.com")
    user.groups.add(group)

    sync_databases(source="local", target="default")

    copied = User.objects.using("default").get(pk=user.pk)
    assert list(copied.groups.values_list("name", flat=True)) == ["learners"]


@BOTH
def test_sequences_are_reset_after_copy():
    for i in range(3):
        Group.objects.using("local").create(name=f"group{i}")
    sync_databases(source="local", target="default")

    fresh = Group.objects.using("default").create(name="new")

    assert fresh.pk > Group.objects.using("local").order_by("-pk").first().pk
