"""Unit under test: `accounts.models`: User (email login, UserManager) and Profile (created with every user).

Why: the email is the login identity. If it isn't normalised and matched case-insensitively, the same person can
register twice or be unable to sign in, and a user without a profile breaks onboarding.

Use cases:
- create_user normalises the email and creates the profile
- an email is required
- create_superuser sets the staff and superuser flags
- looking a user up by email ignores case
- a profile is complete only once the onboarding fields are filled in
"""

import pytest

from accounts.models import Profile, User


@pytest.mark.django_db
def test_create_user_normalises_email_and_creates_profile():
    user = User.objects.create_user("Ada@Example.COM", password="x", name="Ada")

    assert user.email == "ada@example.com"
    assert user.check_password("x")
    assert not user.is_staff
    assert Profile.objects.filter(user=user).exists()


@pytest.mark.django_db
def test_email_is_required():
    with pytest.raises(ValueError):
        User.objects.create_user("", password="x", name="Nobody")


@pytest.mark.django_db
def test_create_superuser_sets_flags():
    admin = User.objects.create_superuser("root@example.com", password="x", name="Root")

    assert admin.is_staff and admin.is_superuser


@pytest.mark.django_db
def test_lookup_by_email_ignores_case():
    user = User.objects.create_user("ada@example.com", password="x", name="Ada")

    assert User.objects.get_by_natural_key("ADA@example.com") == user


@pytest.mark.django_db
def test_profile_complete_needs_the_onboarding_fields(user):
    profile = user.profile
    assert not profile.is_complete

    profile.education_level = Profile.EducationLevel.UNDERGRADUATE
    profile.learning_preference = Profile.LearningPreference.VISUAL
    assert not profile.is_complete

    profile.goal = Profile.Goal.EXAM_PREP
    assert profile.is_complete
