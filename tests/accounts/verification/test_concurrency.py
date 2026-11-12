"""Unit under test: `SignupVerification`, `CodeChecker` and `CodeIssuer` with several real threads (and so several
database connections) at once.

Why: every rule that must hold "when two requests race" is a database rule (a counted `UPDATE`, a unique index, a row
lock, an advisory lock), and a single-threaded test cannot tell a rule from no rule. So these use real threads, real
transactions (`transaction=True`) and a barrier that releases them together, and check what must hold in every
interleaving, not one lucky order.

Use cases:
- **five simultaneous wrong guesses spend five tries**, not one, and kill the code
- **simultaneous correct verifies (eight at once) make one account and one grant**: the others get the plain "no",
  never an error
- an account made by another path between the sign-up and the code: the plain "no", never an error (the race's loser,
  made deterministic)
- two simultaneous registers for one address (the victim's and an attacker's) leave one pending row and one live code,
  and exactly one of the two tickets matches it
- a verify racing a re-register: whichever order, no account is made with the password of a row whose ticket the caller
  does not hold
- two sign-ups for aliases of one inbox leave one pending row and, when finished, one account
- two simultaneous code issues for one email leave exactly one live code
"""

import pytest
from django.contrib.auth.hashers import make_password
from support.mail import MAILBOX
from support.threads import together

from accounts.models import PendingSignup, User, VerificationCode
from accounts.verification.checker import CodeChecker
from accounts.verification.issuer import CodeIssuer
from accounts.verification.signup import SignupRequest, SignupVerification
from credits.models import CreditBucket

pytestmark = pytest.mark.django_db(transaction=True)

VICTIM_PASSWORD, ATTACKER_PASSWORD = "victims-own-password-1", "attackers-own-password-9"


def request(email, password=VICTIM_PASSWORD, name="Grace Hopper"):
    from django.utils import timezone

    return SignupRequest(
        email=email,
        name=name,
        password_hash=make_password(password),
        timezone="",
        terms_version=User.TERMS_VERSION,
        terms_accepted_at=timezone.now(),
    )


def code_sent_to(address):
    return MAILBOX.code_for(address)


def test_five_simultaneous_wrong_guesses_spend_five_tries_and_kill_the_code():
    issued = CodeIssuer().issue("signup", "ada@example.com")
    wrong = "000000" if issued.code != "000000" else "111111"

    results = together([lambda: CodeChecker().check("signup", "ada@example.com", wrong) for _ in range(5)])

    assert not any(isinstance(r, Exception) for r in results), results
    row = VerificationCode.objects.get(pk=issued.row_id)
    assert row.attempts == 5 and row.invalidated_at is not None
    assert not CodeChecker().check("signup", "ada@example.com", issued.code).ok  # the right code is too late


@pytest.mark.parametrize("round_", range(3))
def test_simultaneous_correct_verifies_make_one_account_and_one_grant(round_):
    started = SignupVerification().start(request("ada@example.com"), ip=None)
    code = code_sent_to("ada@example.com")

    confirm = lambda: SignupVerification().confirm("ada@example.com", code, started.ticket)  # noqa: E731
    results = together([confirm for _ in range(8)])

    assert not any(isinstance(r, Exception) for r in results), results
    assert sum(r is not None for r in results) == 1  # one account, seven plain "no"s
    assert User.objects.filter(email_canonical="ada@example.com").count() == 1
    assert CreditBucket.objects.filter(source="signup").count() == 1
    assert not PendingSignup.objects.exists()


def test_two_simultaneous_registers_for_one_address_leave_one_row_one_code_and_one_matching_ticket():
    tickets = together(
        [
            lambda: SignupVerification().start(request("victim@example.com"), ip=None).ticket,
            lambda: (
                SignupVerification().start(request("victim@example.com", ATTACKER_PASSWORD, "Mallory"), ip=None).ticket
            ),
        ]
    )

    assert not any(isinstance(t, Exception) for t in tickets), tickets
    assert PendingSignup.objects.count() == 1
    assert VerificationCode.objects.filter(email_canonical="victim@example.com", invalidated_at=None).count() == 1
    code = code_sent_to("victim@example.com")  # the latest mail: the live code
    confirmed = [SignupVerification().confirm("victim@example.com", code, ticket) for ticket in tickets]
    assert sorted(user is None for user in confirmed) == [False, True]  # exactly one ticket matches the live row


@pytest.mark.parametrize("round_", range(4))
def test_a_verify_racing_a_re_register_never_makes_an_account_with_the_attackers_password(round_):
    verification = SignupVerification()
    started = verification.start(request("victim@example.com"), ip=None)
    victims_code = code_sent_to("victim@example.com")

    together(
        [
            lambda: SignupVerification().confirm("victim@example.com", victims_code, started.ticket),
            lambda: SignupVerification().start(request("victim@example.com", ATTACKER_PASSWORD, "Mallory"), ip=None),
        ]
    )

    for account in User.objects.filter(email_canonical="victim@example.com"):
        assert account.check_password(VICTIM_PASSWORD) and not account.check_password(ATTACKER_PASSWORD)
        assert account.name == "Grace Hopper"


def test_two_sign_ups_for_aliases_of_one_inbox_leave_one_row_and_make_one_account():
    tickets = together(
        [
            lambda: SignupVerification().start(request("a.b+one@gmail.com"), ip=None).ticket,
            lambda: SignupVerification().start(request("ab@googlemail.com"), ip=None).ticket,
        ]
    )

    assert PendingSignup.objects.count() == 1
    code = MAILBOX.messages[-1].text
    digits = [part for part in code.split() if part.isdigit() and len(part) == 6][0]
    users = [SignupVerification().confirm("ab@gmail.com", digits, ticket) for ticket in tickets]
    assert sorted(u is None for u in users) == [False, True] and User.objects.count() == 1


def test_two_simultaneous_issues_for_one_email_leave_exactly_one_live_code():
    results = together([lambda: CodeIssuer().issue("signup", "ada@example.com") for _ in range(4)])

    assert not any(isinstance(r, Exception) for r in results), results
    live = VerificationCode.objects.filter(email_canonical="ada@example.com", invalidated_at=None, consumed_at=None)
    assert live.count() == 1
    assert VerificationCode.objects.filter(email_canonical="ada@example.com").count() == 4


def test_an_account_that_took_the_address_after_the_code_was_asked_for_gives_the_plain_no_not_an_error():
    """The race's loser, made deterministic: another path made the account between the sign-up and the code. The unique
    column refuses the second account and the person is told the same "no", never a server error."""
    started = SignupVerification().start(request("ada@example.com"), ip=None)
    code = code_sent_to("ada@example.com")
    User.objects.create_user("Ada@example.com", password="x" * 12, name="Someone else", verified=True)

    assert SignupVerification().confirm("ada@example.com", code, started.ticket) is None

    assert User.objects.filter(email_canonical="ada@example.com").count() == 1
    assert CreditBucket.objects.filter(source="signup").count() == 0
