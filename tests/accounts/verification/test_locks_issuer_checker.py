"""Unit under test: `EmailLocks`, `CodeIssuer` and `CodeChecker` (`accounts.verification`), the rules every emailed code
lives by (plan 5.6, D10, T9).

Why: a six-digit code is a password for ten minutes, so everything around it is what makes it safe: it works once, it
dies after five wrong tries, a new one cancels the old, an address that keeps killing codes is paused, and every
failure looks the same (no hint whether the address exists, the code was wrong, old or used). Time comes from a fake
clock; nothing sleeps.

Use cases:
- issuing makes a live code of the configured length that is stored only as a hash, valid for the configured time
- a new code for the same purpose and email cancels the old one; other purposes and emails are untouched
- the right code is consumed once and a second use fails
- a wrong code spends a try; the fifth wrong try kills the code even for the right code after it
- an expired code, a cancelled code, no code and a never-asked email all fail the same way
- **the attempt is counted before the code is compared**: a try is spent on a wrong code, and a code with no tries left
  is refused without being compared (the right code then fails too)
- three dead codes within the window lock the email for the window; the lock ends, can be cleared, and strikes older
  than the window are forgotten
- a locked email checks no codes at all, the right one included
- the lock is keyed on the canonical email, whether or not an account has it
"""

from datetime import timedelta

import pytest
from support.clock import FakeClock

from accounts.models import EmailLock, VerificationCode
from accounts.verification.checker import CodeChecker
from accounts.verification.config import VerificationSettings
from accounts.verification.issuer import CodeIssuer
from accounts.verification.locks import EmailLocks

pytestmark = pytest.mark.django_db

EMAIL = "ada@example.com"
SIGNUP = VerificationCode.Purpose.SIGNUP
LOGIN = VerificationCode.Purpose.LOGIN


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def config():
    return VerificationSettings()


@pytest.fixture
def issuer(clock, config):
    return CodeIssuer(clock=clock, settings=config)


@pytest.fixture
def checker(clock, config):
    return CodeChecker(clock=clock, locks=EmailLocks(clock, config))


def wrong(code):
    return "000000" if code != "000000" else "111111"


# --- issuing ---


def test_issuing_makes_a_live_code_stored_only_as_a_hash(issuer, clock):
    issued = issuer.issue(SIGNUP, EMAIL, ip="203.0.113.5")

    row = VerificationCode.objects.get(pk=issued.row_id)
    assert len(issued.code) == 6 and issued.code.isdigit()
    assert issued.minutes == 10 and row.expires_at == clock.now() + timedelta(minutes=10)
    assert issued.code not in row.code_hash and issued.code not in str(row.__dict__)
    assert (row.attempts, row.max_attempts, row.consumed_at, row.invalidated_at) == (0, 5, None, None)
    assert row.requested_ip == "203.0.113.5"


def test_the_code_length_comes_from_the_settings(clock):
    issuer = CodeIssuer(clock=clock, settings=VerificationSettings(code_digits=8))

    assert len(issuer.issue(SIGNUP, EMAIL).code) == 8


def test_a_new_code_cancels_the_old_one_for_the_same_purpose_and_email_only(issuer):
    first = issuer.issue(SIGNUP, EMAIL)
    other_purpose = issuer.issue(LOGIN, EMAIL)
    other_email = issuer.issue(SIGNUP, "grace@example.com")

    second = issuer.issue(SIGNUP, EMAIL)

    assert VerificationCode.objects.get(pk=first.row_id).invalidated_at is not None
    assert VerificationCode.objects.filter(purpose=SIGNUP, email_canonical=EMAIL, invalidated_at=None).count() == 1
    assert VerificationCode.objects.get(pk=second.row_id).invalidated_at is None
    assert VerificationCode.objects.get(pk=other_purpose.row_id).invalidated_at is None
    assert VerificationCode.objects.get(pk=other_email.row_id).invalidated_at is None


# --- checking ---


def test_the_right_code_is_consumed_once(issuer, checker, clock):
    issued = issuer.issue(SIGNUP, EMAIL)

    first = checker.check(SIGNUP, EMAIL, issued.code)
    second = checker.check(SIGNUP, EMAIL, issued.code)

    assert first.ok and first.row.pk == issued.row_id
    assert not second.ok
    assert VerificationCode.objects.get(pk=issued.row_id).consumed_at == clock.now()


def test_a_code_for_another_purpose_or_email_does_not_work(issuer, checker):
    issued = issuer.issue(SIGNUP, EMAIL)

    assert not checker.check(LOGIN, EMAIL, issued.code).ok
    assert not checker.check(SIGNUP, "grace@example.com", issued.code).ok
    assert checker.check(SIGNUP, EMAIL, issued.code).ok  # still good for what it was made for


def test_a_wrong_code_spends_a_try_and_the_fifth_wrong_try_kills_the_code(issuer, checker):
    issued = issuer.issue(SIGNUP, EMAIL)

    for tries in range(1, 6):
        assert not checker.check(SIGNUP, EMAIL, wrong(issued.code)).ok
        assert VerificationCode.objects.get(pk=issued.row_id).attempts == tries

    row = VerificationCode.objects.get(pk=issued.row_id)
    assert row.invalidated_at is not None
    assert not checker.check(SIGNUP, EMAIL, issued.code).ok  # the right code is too late
    assert VerificationCode.objects.get(pk=issued.row_id).attempts == 5  # and spent no sixth try


def test_the_right_code_on_the_fifth_try_still_works(issuer, checker):
    issued = issuer.issue(SIGNUP, EMAIL)
    for _ in range(4):
        checker.check(SIGNUP, EMAIL, wrong(issued.code))

    assert checker.check(SIGNUP, EMAIL, issued.code).ok


def test_the_try_is_counted_before_the_code_is_compared(issuer, checker):
    """A code with no tries left is refused without a comparison: the guard is the database's, not the compare's."""
    issued = issuer.issue(SIGNUP, EMAIL)
    VerificationCode.objects.filter(pk=issued.row_id).update(attempts=5)  # five tries spent, not yet marked dead

    assert not checker.check(SIGNUP, EMAIL, issued.code).ok  # right code, no tries left

    assert VerificationCode.objects.get(pk=issued.row_id).consumed_at is None


def test_an_expired_code_fails(issuer, checker, clock):
    issued = issuer.issue(SIGNUP, EMAIL)
    clock.advance(minutes=10, seconds=1)

    assert not checker.check(SIGNUP, EMAIL, issued.code).ok


def test_a_code_works_right_up_to_its_last_minute(issuer, checker, clock):
    issued = issuer.issue(SIGNUP, EMAIL)
    clock.advance(minutes=9, seconds=59)

    assert checker.check(SIGNUP, EMAIL, issued.code).ok


def test_every_failure_looks_the_same(issuer, checker, clock):
    cancelled = issuer.issue(SIGNUP, "a@example.com")
    issuer.issue(SIGNUP, "a@example.com")
    used = issuer.issue(SIGNUP, "b@example.com")
    checker.check(SIGNUP, "b@example.com", used.code)
    results = [
        checker.check(SIGNUP, "a@example.com", cancelled.code),  # cancelled
        checker.check(SIGNUP, "b@example.com", used.code),  # used
        checker.check(SIGNUP, "nobody@example.com", "123456"),  # never asked
        checker.check(SIGNUP, "a@example.com", wrong(cancelled.code)),  # wrong
    ]

    assert all(result == CodeChecker.FAILED for result in results)


# --- locks ---


def test_three_dead_codes_lock_the_email_and_the_lock_ends(issuer, checker, clock):
    locks = EmailLocks(clock)
    for _ in range(3):
        issued = issuer.issue(SIGNUP, EMAIL)
        for _ in range(5):
            checker.check(SIGNUP, EMAIL, wrong(issued.code))
    assert locks.is_locked(EMAIL)

    clock.advance(minutes=59)
    assert locks.is_locked(EMAIL)
    clock.advance(minutes=2)
    assert not locks.is_locked(EMAIL)


def test_a_locked_email_checks_no_codes_the_right_one_included(issuer, checker, clock):
    for _ in range(3):
        issued = issuer.issue(SIGNUP, EMAIL)
        for _ in range(5):
            checker.check(SIGNUP, EMAIL, wrong(issued.code))
    fresh = issuer.issue(SIGNUP, EMAIL)

    assert not checker.check(SIGNUP, EMAIL, fresh.code).ok
    assert VerificationCode.objects.get(pk=fresh.row_id).attempts == 0  # a locked email does not even count tries

    EmailLocks(clock).clear(EMAIL)
    assert checker.check(SIGNUP, EMAIL, fresh.code).ok


def test_two_dead_codes_do_not_lock_and_old_strikes_are_forgotten(clock, config):
    locks = EmailLocks(clock, config)
    locks.strike(EMAIL)
    locks.strike(EMAIL)
    assert not locks.is_locked(EMAIL)

    clock.advance(minutes=61)  # the first two are older than the window
    locks.strike(EMAIL)

    assert not locks.is_locked(EMAIL) and EmailLock.objects.get(email_canonical=EMAIL).strikes == 1


def test_the_lock_is_a_row_keyed_on_the_email_whether_or_not_an_account_has_it(clock, config):
    locks = EmailLocks(clock, config)
    for _ in range(3):
        locks.strike("nobody-has-this@example.com")

    row = EmailLock.objects.get(email_canonical="nobody-has-this@example.com")
    assert row.locked_until == clock.now() + timedelta(hours=1)
    assert locks.is_locked("nobody-has-this@example.com") and not locks.is_locked("someone-else@example.com")
