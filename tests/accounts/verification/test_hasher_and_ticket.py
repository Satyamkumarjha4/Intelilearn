"""Unit under test: `accounts.verification.hasher.CodeHasher` and `accounts.verification.ticket.SignupTicket`, the two
small keyed values of the sign-up flow.

Why: a code is stored only as a keyed hash that cannot be moved to another row or person, and the signup ticket is the
only thing that ties a pending sign-up to the browser that made it. A hash that did not depend on the row, or a ticket
that could be forged, replayed after its time or used for another row, would reopen the door the design closes (someone
re-registering a victim's address with their own password).

Use cases:
- the same inputs give the same hash, and the stored value is not the code
- any change of code, purpose, email or row id changes the hash, so a hash cannot be moved
- `matches` accepts the right code and refuses a wrong one
- a ticket reads back as the pending id it was made for
- a missing, empty, tampered, foreign-key or expired ticket reads as nothing
- a decoy ticket is a valid ticket for a row that does not exist
"""

import time
import uuid
from datetime import timedelta

import pytest
from django.core import signing

from accounts.verification.config import VerificationSettings
from accounts.verification.hasher import CodeHasher
from accounts.verification.ticket import SignupTicket

ROW = uuid.UUID("11111111-1111-4111-8111-111111111111")


def test_the_same_inputs_give_the_same_hash_and_it_is_not_the_code():
    hasher = CodeHasher()
    stored = hasher.hash("123456", "signup", "ada@example.com", ROW)

    assert stored == hasher.hash("123456", "signup", "ada@example.com", ROW)
    assert "123456" not in stored and len(stored) == 64


@pytest.mark.parametrize(
    "change",
    [
        {"code": "123457"},
        {"purpose": "login"},
        {"email_canonical": "grace@example.com"},
        {"row_id": uuid.UUID("22222222-2222-4222-8222-222222222222")},
    ],
)
def test_any_change_of_code_purpose_email_or_row_changes_the_hash(change):
    base = {"code": "123456", "purpose": "signup", "email_canonical": "ada@example.com", "row_id": ROW}
    hasher = CodeHasher()

    assert hasher.hash(**base) != hasher.hash(**{**base, **change})


def test_matches_accepts_the_right_code_and_refuses_a_wrong_one():
    hasher = CodeHasher()
    stored = hasher.hash("123456", "signup", "ada@example.com", ROW)

    assert hasher.matches("123456", stored, "signup", "ada@example.com", ROW)
    assert not hasher.matches("654321", stored, "signup", "ada@example.com", ROW)
    assert not hasher.matches("123456", stored, "login", "ada@example.com", ROW)  # a hash cannot be moved to a purpose
    assert not hasher.matches("123456", stored, "signup", "ada@example.com", uuid.uuid4())  # ... or to another row


def test_a_ticket_reads_back_as_the_pending_id_it_was_made_for():
    tickets = SignupTicket()

    assert tickets.read(tickets.issue(ROW)) == ROW


@pytest.mark.parametrize("token", [None, "", "garbage", "abc:def:ghi"])
def test_a_missing_or_malformed_ticket_reads_as_nothing(token):
    assert SignupTicket().read(token) is None


def test_a_tampered_ticket_reads_as_nothing():
    tickets = SignupTicket()
    token = tickets.issue(ROW)
    value, _, rest = token.partition(":")

    assert tickets.read(f"{signing.b64_encode(str(uuid.uuid4()).encode()).decode()}:{rest}") is None
    assert tickets.read(token[:-3] + "xxx") is None
    assert value  # the untouched one still works
    assert tickets.read(token) == ROW


def test_a_ticket_signed_for_another_purpose_is_not_a_ticket():
    foreign = signing.dumps(str(ROW), salt="accounts.something-else", compress=False)

    assert SignupTicket().read(foreign) is None


def test_an_expired_ticket_reads_as_nothing(monkeypatch):
    tickets = SignupTicket(VerificationSettings(ticket_ttl=timedelta(minutes=5)))
    token = tickets.issue(ROW)
    assert tickets.read(token) == ROW

    later = time.time() + 6 * 60
    monkeypatch.setattr("django.core.signing.time.time", lambda: later)  # the clock the signer reads

    assert tickets.read(token) is None


def test_a_decoy_ticket_is_valid_but_is_for_a_row_that_does_not_exist():
    tickets = SignupTicket()
    decoy = tickets.read(tickets.decoy())

    assert isinstance(decoy, uuid.UUID) and decoy != ROW
