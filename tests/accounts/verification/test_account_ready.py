"""Unit under test: `AccountActivation.announce`, the one place `account_ready` is sent (plan T15), as the sign-up code
check and the login code check use it.

Why: the 30 signup credits hang from `account_ready`. Two rules must hold however the code is called. A receiver that
fails (a bug, a database error) must never remove or roll back the account that was just made: the person exists, and
what the receiver does can be run again. And no receiver, so no grant, may run for an account that was never
committed: a caller's transaction that rolls back after the code check must leave no credits behind for a person who
does not exist. Both are what "send after the account is committed" means, so each is shown with a real outer
transaction and real threads' connection semantics (`transaction=True`).

Use cases:
- a receiver that raises a Python error does not remove the account, and the other receivers still run
- a receiver that makes the database fail (a statement error) inside the caller's transaction does not roll the account
  back: the account is committed and the receiver ran after it
- when the caller's transaction rolls back after the code check, there is no account, no grant row and no receiver call
- the receiver runs exactly once, after the commit, and sees the committed account
- the login code check (an existing account proving its email) announces the same way
"""

import pytest
from django.contrib.auth.hashers import make_password
from django.db import connection, transaction
from django.utils import timezone
from support.mail import MAILBOX

from accounts.models import User
from accounts.signals import account_ready
from accounts.verification.login import LoginVerification
from accounts.verification.signup import SignupRequest, SignupVerification
from credits.models import CreditBucket, CreditTransaction

pytestmark = pytest.mark.django_db(transaction=True)


class Boom(Exception):
    pass


@pytest.fixture
def receivers():
    """Connect receivers for one test; they are disconnected after it."""
    connected = []

    def connect(receiver):
        account_ready.connect(receiver, weak=False, dispatch_uid=f"test-{len(connected)}")
        connected.append(receiver)
        return receiver

    yield connect
    for index, receiver in enumerate(connected):
        account_ready.disconnect(receiver, dispatch_uid=f"test-{index}")


def started(email="ada@example.com"):
    request = SignupRequest(
        email=email,
        name="Ada",
        password_hash=make_password("a-long-password-1"),
        timezone="",
        terms_version=User.TERMS_VERSION,
        terms_accepted_at=timezone.now(),
    )
    ticket = SignupVerification().start(request, ip=None).ticket
    return ticket, MAILBOX.code_for(email)


def test_a_receiver_that_raises_does_not_remove_the_account_and_the_others_still_run(receivers):
    ran = []

    def broken(sender, **kwargs):
        raise Boom("a receiver bug")

    receivers(broken)
    receivers(lambda sender, **kwargs: ran.append(kwargs["user"].email))
    ticket, code = started()

    user = SignupVerification().confirm("ada@example.com", code, ticket)

    assert user is not None and User.objects.filter(email_canonical="ada@example.com").exists()
    assert "ada@example.com" in ran


def test_a_receiver_that_makes_the_database_fail_inside_the_callers_transaction_does_not_roll_the_account_back(
    receivers,
):
    ran = []

    def database_error(sender, **kwargs):
        ran.append(kwargs["user"].pk)
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 / 0")  # a statement error: inside a transaction it would poison the whole of it

    receivers(database_error)
    ticket, code = started()

    with transaction.atomic():  # an outer transaction, as a caller that wraps the check in its own would have
        user = SignupVerification().confirm("ada@example.com", code, ticket)

    assert user is not None and ran == [user.pk]
    assert User.objects.filter(email_canonical="ada@example.com").exists()  # committed, and the receiver ran after it


def test_when_the_callers_transaction_rolls_back_there_is_no_account_no_grant_and_no_receiver_call(receivers):
    calls = []
    receivers(lambda sender, **kwargs: calls.append(kwargs["user"].pk))
    ticket, code = started()

    with pytest.raises(Boom):
        with transaction.atomic():
            assert SignupVerification().confirm("ada@example.com", code, ticket) is not None
            raise Boom("the caller's later step failed")

    assert not User.objects.filter(email_canonical="ada@example.com").exists()
    assert not CreditBucket.objects.exists() and not CreditTransaction.objects.exists()  # no grant without its account
    assert calls == []  # and nothing was told an account is ready that does not exist


def test_the_receiver_runs_once_after_the_commit_and_sees_the_committed_account(receivers):
    seen = []

    def receiver(sender, **kwargs):
        seen.append((kwargs["user"].pk, User.objects.filter(pk=kwargs["user"].pk).exists(), connection.in_atomic_block))

    receivers(receiver)
    ticket, code = started()

    user = SignupVerification().confirm("ada@example.com", code, ticket)

    assert seen == [(user.pk, True, False)]  # once, the account is there, and no transaction is still open
    assert CreditBucket.objects.get(user=user).amount_granted == 30  # and the real grant receiver gave the credits


def test_the_login_code_check_announces_the_same_way(receivers):
    calls = []
    receivers(lambda sender, **kwargs: calls.append((kwargs["user"].pk, connection.in_atomic_block)))
    account = User.objects.create_user("unproved@example.com", password="a-long-password-1", name="Unproved")
    LoginVerification().start(account)
    code = MAILBOX.code_for("unproved@example.com", "login_code")

    with pytest.raises(Boom):
        with transaction.atomic():
            LoginVerification().confirm("unproved@example.com", code)
            raise Boom("rolled back")
    account.refresh_from_db()
    assert not account.is_email_verified and calls == []  # verified and announced only if committed

    LoginVerification().start(account)
    LoginVerification().confirm("unproved@example.com", MAILBOX.code_for("unproved@example.com", "login_code"))
    assert calls == [(account.pk, False)]
