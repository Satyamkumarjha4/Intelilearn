"""Unit under test: `manage.py audit_seed` (backend/core/management/commands/audit_seed.py).

Why: it is the one command that makes accounts with a known password, so what it prints and when it refuses matter:
the persona names and addresses are for the auditors, a password is never printed, and anywhere that is not a
throwaway stack it stops with a plain message instead of a traceback.

Use cases:
- `--only` with `--skip-history` makes those personas and prints their slugs, addresses and what each has, and never
  a password
- running it again says the personas were already there
- outside DEBUG it stops with a message (a CommandError), makes nothing, and does not print the password
"""

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from accounts.models import User
from credits.ledger import Ledger

pytestmark = pytest.mark.django_db

PASSWORD = "audit-test-password-1"


@pytest.fixture
def on_a_throwaway_stack(settings, monkeypatch):
    settings.DEBUG = True
    settings.USING_SUPABASE = False
    monkeypatch.setenv("AUDIT_PERSONA_PASSWORD", PASSWORD)
    monkeypatch.setattr("django.db.transaction.on_commit", lambda func, using=None, robust=False: func())


def run(*args) -> str:
    out = StringIO()
    call_command("audit_seed", *args, stdout=out)
    return out.getvalue()


def test_it_makes_the_chosen_personas_and_prints_names_and_addresses_but_no_password(on_a_throwaway_stack):
    output = run("--only", "zero-credits", "staff", "--skip-history")

    assert "audit-zero-credits@example.test" in output and "audit-staff@example.test" in output
    assert "2 personas ready" in output and PASSWORD not in output
    assert Ledger().balance(User.objects.get(email="audit-zero-credits@example.test")) == 0
    assert User.objects.get(email="audit-staff@example.test").is_staff


def test_running_it_again_says_the_personas_were_already_there(on_a_throwaway_stack):
    run("--only", "staff")

    assert "already there" in run("--only", "staff")


def test_outside_debug_it_stops_with_a_message_and_makes_nothing(on_a_throwaway_stack, settings):
    settings.DEBUG = False

    with pytest.raises(CommandError, match="DJANGO_DEBUG") as stopped:
        run("--only", "staff")

    assert PASSWORD not in str(stopped.value) and not User.objects.filter(email__startswith="audit-").exists()
