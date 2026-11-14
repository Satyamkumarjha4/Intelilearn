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
- the records behind the abuse board (how accounts were made, the events, the switch) can be listed and looked at in the
  admin but not added, changed or deleted there, so nothing can be forged or removed to hide what happened
"""

import pytest
from django.urls import reverse

from accounts.models import AuthEvent, AuthSettings, SignupRecord

pytestmark = pytest.mark.django_db


def test_the_change_form_shows_the_email_read_only(admin_client, user):
    response = admin_client.get(reverse("admin:accounts_user_change", args=[user.pk]))

    form = response.context["adminform"]
    assert "email" not in form.form.fields
    assert {"email", "email_verified_at", "email_verification_source", "email_canonical"} <= set(form.readonly_fields)


def test_the_add_form_lets_the_email_be_typed(admin_client):
    response = admin_client.get(reverse("admin:accounts_user_add"))

    assert "email" in response.context["adminform"].form.fields


@pytest.fixture
def records(user):
    SignupRecord.objects.create(user=user, ip="203.0.113.1", email_domain="example.com", method="code")
    event = AuthEvent.objects.create(kind="check_failed", ip="203.0.113.2", email_domain="example.com")
    AuthSettings.objects.update_or_create(pk=1, defaults={"captcha_enabled": False})
    return {"signuprecord": SignupRecord.objects.get(), "authevent": event, "authsettings": AuthSettings.load()}


@pytest.mark.parametrize("model", ["signuprecord", "authevent", "authsettings"])
def test_the_abuse_records_can_be_listed_and_read_but_not_changed(admin_client, records, model):
    row = records[model]

    listed = admin_client.get(reverse(f"admin:accounts_{model}_changelist"))
    viewed = admin_client.get(reverse(f"admin:accounts_{model}_change", args=[row.pk]))
    added = admin_client.get(reverse(f"admin:accounts_{model}_add"))
    deleted = admin_client.post(reverse(f"admin:accounts_{model}_delete", args=[row.pk]), {"post": "yes"})
    changed = admin_client.post(reverse(f"admin:accounts_{model}_change", args=[row.pk]), {"captcha_enabled": "on"})

    assert listed.status_code == 200 and viewed.status_code == 200
    assert added.status_code == 403 and deleted.status_code == 403 and changed.status_code == 403
    assert type(row).objects.filter(pk=row.pk).exists() and AuthSettings.load().captcha_enabled is False


def test_an_event_cannot_be_removed_by_the_bulk_delete_action(admin_client, records):
    response = admin_client.post(
        reverse("admin:accounts_authevent_changelist"),
        {"action": "delete_selected", "_selected_action": [records["authevent"].pk], "post": "yes"},
    )

    assert response.status_code in (200, 302) and AuthEvent.objects.filter(pk=records["authevent"].pk).exists()
