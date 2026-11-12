"""Unit under test: `accounts.emailrules.policy` (`EmailPolicy`, `WellFormed`, `NotDisposable`).

Why: who may sign up is decided by a chain of small rules, so a new rule is a new class and the chain never grows an
`if`. A refusal says what to do in a learner's words and must not teach people which domains to avoid or reveal
anything about whether an account exists (the policy never looks at accounts).

Use cases:
- a well-formed ordinary address passes and the policy returns its canonical form
- a malformed address is refused with the plain message
- a disposable address is refused with a message that does not name a list, and a school address on the blocklist passes
- rules run in order and a new rule can be added without changing the policy
"""

import pytest

from accounts.emailrules.disposable import DisposableDomains
from accounts.emailrules.policy import EmailPolicy, EmailRefused, EmailRule, NotDisposable, WellFormed

DOMAINS = DisposableDomains({"mailinator.com", "ac.in"}, allowed={"ac.in"})


def test_a_good_address_passes_and_the_canonical_form_comes_back():
    policy = EmailPolicy((WellFormed(), NotDisposable(DOMAINS)))

    assert policy.check("Ada.Lovelace+x@Gmail.com") == "adalovelace@gmail.com"


@pytest.mark.parametrize("address", ["", "nobody", "@example.com", "ada@", "+x@example.com"])
def test_a_malformed_address_is_refused_plainly(address):
    with pytest.raises(EmailRefused) as refused:
        EmailPolicy((WellFormed(), NotDisposable(DOMAINS))).check(address)

    assert refused.value.message == WellFormed.MESSAGE


def test_a_disposable_address_is_refused_without_naming_a_list():
    with pytest.raises(EmailRefused) as refused:
        EmailPolicy((WellFormed(), NotDisposable(DOMAINS))).check("ada@mailinator.com")

    message = refused.value.message
    assert message == NotDisposable.MESSAGE
    assert "list" not in message.lower() and "mailinator" not in message.lower()


def test_a_school_address_on_the_blocklist_still_passes():
    assert EmailPolicy((WellFormed(), NotDisposable(DOMAINS))).check("student@school.ac.in") == "student@school.ac.in"


def test_rules_run_in_order_and_a_new_rule_is_just_a_class():
    seen = []

    class Noting(EmailRule):
        def __init__(self, name):
            self.name = name

        def check(self, email):
            seen.append(self.name)

    class Refusing(EmailRule):
        def check(self, email):
            raise EmailRefused("no")

    EmailPolicy((Noting("a"), Noting("b"))).check("ada@example.com")
    with pytest.raises(EmailRefused):
        EmailPolicy((Noting("c"), Refusing(), Noting("never"))).check("ada@example.com")

    assert seen == ["a", "b", "c"]
