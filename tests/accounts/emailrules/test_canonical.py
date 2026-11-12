"""Unit under test: `accounts.emailrules.canonical.EmailCanonicalizer`, the one place that says when two addresses are
the same inbox.

Why: one person, one account. The 30 signup credits are given once per account, so an address that can be written
many ways
(`a.b+1@gmail.com`, `ab@googlemail.com`) would be many accounts and many grants for one inbox. The canonical form
is used
only to decide "have we seen this person" (uniqueness, throttle keys, lookups); the address as typed is what mail
goes to.
Getting a rule wrong in one direction lets one person farm; in the other it locks two real people into one account, so
what must NOT change is held by tests as much as what must.

Use cases:
- case is ignored, in the domain and in the local part, and spaces around the address are trimmed
- everything from the first `+` in the local part is dropped, for every domain
- for gmail.com and googlemail.com the dots of the local part are dropped too, and googlemail.com is gmail.com
- the dots of any other domain's local part are kept (a Yahoo or college dot is meaningful), and so is a gmail
  subdomain's
- an address with nothing before the `+`, no `@`, no local part or no domain is malformed
- the canonical form of a canonical form is itself
"""

import pytest

from accounts.emailrules.canonical import EmailCanonicalizer, MalformedEmail


@pytest.mark.parametrize(
    ("typed", "canonical"),
    [
        ("ada@example.com", "ada@example.com"),
        ("Ada@Example.COM", "ada@example.com"),
        ("  ada@example.com  ", "ada@example.com"),
        ("ada+tag@example.com", "ada@example.com"),
        ("ada+a+b@example.com", "ada@example.com"),
        ("ada+@example.com", "ada@example.com"),
        ("A.B+tag@Gmail.com", "ab@gmail.com"),
        ("a.b.c@gmail.com", "abc@gmail.com"),
        ("ab@googlemail.com", "ab@gmail.com"),
        ("A.B@GoogleMail.com", "ab@gmail.com"),
        ("a.b+x@googlemail.com", "ab@gmail.com"),
        ("a.b@yahoo.com", "a.b@yahoo.com"),
        ("first.last@college.ac.in", "first.last@college.ac.in"),
        ("a.b@mail.gmail.com", "a.b@mail.gmail.com"),
        ("Ada@Bücher.de", "ada@bücher.de"),
        ('"a@b"@example.com', '"a@b"@example.com'),
    ],
)
def test_the_canonical_form_of_an_address(typed, canonical):
    assert EmailCanonicalizer.of(typed) == canonical


@pytest.mark.parametrize("typed", ["+x@example.com", "ada", "@example.com", "ada@", "", "   ", "+@gmail.com"])
def test_a_malformed_address_is_refused(typed):
    with pytest.raises(MalformedEmail):
        EmailCanonicalizer.of(typed)


def test_the_canonical_form_of_a_canonical_form_is_itself():
    for typed in ["A.B+tag@Gmail.com", "ab@googlemail.com", "Ada+x@Example.com", "a.b@yahoo.com"]:
        once = EmailCanonicalizer.of(typed)
        assert EmailCanonicalizer.of(once) == once


def test_the_same_inbox_written_differently_is_one_canonical_address():
    forms = ["a.b+1@gmail.com", "ab@gmail.com", "A.B@googlemail.com", "ab+promo@GMAIL.com"]

    assert len({EmailCanonicalizer.of(form) for form in forms}) == 1
