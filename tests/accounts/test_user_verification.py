"""Unit under test: the verification fields of `accounts.models.User` (`email_verified_at`, `email_verification_source`,
`email_canonical`) and how `UserManager` and `User.save()` keep them true.

Why: the signup credits are given only for a verified email (phase 11), one account per inbox. So an account must say
whether and how its email was proved; two spellings of one inbox must not be two accounts; and an address nobody proved
must never keep a "verified" flag that belonged to another address. Nothing in the app can change a learner's email
today,
so the rule that clears the proof when an email changes is defence in depth for the day some path does.

Use cases:
- a user made the ordinary way is unverified, with no source
- `create_user(verified=True)` and `create_superuser` stamp the time and the source `operator`
- the canonical email is filled on every save (manager or plain `save()`), and a malformed address does not stop a save
- two spellings of one inbox cannot both be saved (the unique column holds it, not only a form)
- an email that was typed with capitals is looked up case-insensitively and by its alias spelling's canonical form
- changing a saved user's email recomputes the canonical form and clears the proof, also when only `update_fields`
  names the email
- saving a user without changing the email, or changing only the name, keeps the proof
- the sources that count as "the owner proved it" are exactly code, google and microsoft
"""

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts.models import User

pytestmark = pytest.mark.django_db


def test_a_user_made_the_ordinary_way_is_unverified():
    user = User.objects.create_user("ada@example.com", password="x", name="Ada")

    assert user.email_verified_at is None
    assert user.email_verification_source == ""
    assert not user.is_email_verified


def test_create_user_can_stamp_the_proof():
    before = timezone.now()

    user = User.objects.create_user("ada@example.com", password="x", name="Ada", verified=True)

    assert before <= user.email_verified_at <= timezone.now()
    assert user.email_verification_source == User.VerificationSource.OPERATOR
    assert user.is_email_verified


def test_create_superuser_is_verified_by_the_operator():
    admin = User.objects.create_superuser("root@example.com", password="x", name="Root")

    assert admin.is_email_verified
    assert admin.email_verification_source == User.VerificationSource.OPERATOR


def test_the_canonical_email_is_filled_by_the_manager_and_by_a_plain_save():
    made = User.objects.create_user("A.B+tag@Gmail.com", password="x", name="Ab")
    plain = User(email="Carl@Example.com", name="Carl")
    plain.save()

    assert made.email_canonical == "ab@gmail.com"
    assert plain.email_canonical == "carl@example.com"


def test_a_malformed_address_does_not_stop_a_save():
    user = User(email="no-at-sign", name="Odd")

    user.save()

    assert user.email_canonical == "no-at-sign"  # forms and serializers judge addresses; the model must not crash


def test_two_spellings_of_one_inbox_cannot_both_be_saved():
    User.objects.create_user("a.b@gmail.com", password="x", name="One")

    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.create_user("ab+second@googlemail.com", password="x", name="Two")

    assert User.objects.count() == 1


def test_lookup_by_email_ignores_case():
    user = User.objects.create_user("ada@example.com", password="x", name="Ada")

    assert User.objects.get_by_natural_key("ADA@Example.com") == user


def test_changing_a_saved_users_email_clears_the_proof_and_recomputes_the_canonical_form():
    user = User.objects.create_user("ada@example.com", password="x", name="Ada", verified=True)
    user.email_verification_source = User.VerificationSource.CODE
    user.save()

    user.email = "Other+x@Example.com"
    user.save()

    user.refresh_from_db()
    assert user.email_canonical == "other@example.com"
    assert user.email_verified_at is None and user.email_verification_source == ""


def test_the_proof_is_also_cleared_when_only_update_fields_names_the_email():
    user = User.objects.create_user("ada@example.com", password="x", name="Ada", verified=True)

    user.email = "grace@example.com"
    user.save(update_fields=["email"])

    stored = User.objects.get(pk=user.pk)
    assert stored.email_canonical == "grace@example.com"
    assert stored.email_verified_at is None and stored.email_verification_source == ""


def test_saving_without_changing_the_email_keeps_the_proof():
    user = User.objects.create_user("ada@example.com", password="x", name="Ada", verified=True)

    user.name = "Ada L"
    user.save()
    user.save(update_fields=["name"])

    stored = User.objects.get(pk=user.pk)
    assert stored.is_email_verified and stored.email_canonical == "ada@example.com"


def test_a_user_read_back_and_saved_unchanged_keeps_the_proof():
    User.objects.create_user("ada@example.com", password="x", name="Ada", verified=True)

    again = User.objects.get(email="ada@example.com")
    again.save()

    assert User.objects.get(pk=again.pk).is_email_verified


def test_refreshing_from_the_database_does_not_make_the_next_save_look_like_a_change():
    user = User.objects.create_user("ada@example.com", password="x", name="Ada", verified=True)
    User.objects.filter(pk=user.pk).update(email="ada.new@example.com", email_canonical="ada.new@example.com")

    user.refresh_from_db()
    user.save()

    assert User.objects.get(pk=user.pk).is_email_verified


def test_only_code_google_and_microsoft_count_as_proved_by_the_owner():
    Source = User.VerificationSource

    proved = {
        s for s in Source if User(email_verification_source=s, email_verified_at=timezone.now()).email_proved_by_owner
    }

    assert proved == {Source.CODE, Source.GOOGLE, Source.MICROSOFT}
    assert not User(email_verification_source=Source.CODE).email_proved_by_owner  # a source without a time is no proof
