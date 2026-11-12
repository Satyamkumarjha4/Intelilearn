"""Unit under test: `accounts.admin.UserAdmin`, the Django admin's form for an account.

Why: nothing lets a learner change their email, and the signup credits go only for a verified one (phase 11). The
admin is
the one form a person with the keys could still change an email on, which would leave the canonical email and the proof
describing an address that is gone. So the email is typed when an account is added and is read-only afterwards, and the
three verification fields are shown but never editable.

Use cases:
- the change form shows the email but does not let it be edited
- the add form lets the email be typed
- the verification fields (verified time, source, canonical email) are shown read-only on the change form
"""

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_the_change_form_shows_the_email_read_only(admin_client, user):
    response = admin_client.get(reverse("admin:accounts_user_change", args=[user.pk]))

    form = response.context["adminform"]
    assert "email" not in form.form.fields
    assert {"email", "email_verified_at", "email_verification_source", "email_canonical"} <= set(form.readonly_fields)


def test_the_add_form_lets_the_email_be_typed(admin_client):
    response = admin_client.get(reverse("admin:accounts_user_add"))

    assert "email" in response.context["adminform"].form.fields
