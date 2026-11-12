"""Unit under test: `POST /api/auth/register`, `/api/auth/verify` and `/api/auth/verify/resend`, and the sign-in of an
account whose email was never proved (`POST /api/auth/login` answering `403 verification_required`), in
`accounts.views`.

Why: this is what stops free-credit farming. An account exists only once a code that went to the address comes back, in
the browser that asked for it, and the answers say as little as possible: one `invalid_code` for every failure, the same
reply for an address that has an account and one that does not, and nothing sent to a stranger. Each rule here is a
test that fails if the rule is removed.

Use cases:
- a wrong, expired, used, killed or never-asked code, a missing, forged or stale ticket and a body that does not parse
  all answer the identical `400 invalid_code`
- the right code with the right ticket makes the account and signs in; the ticket is spent and cannot be used again
- five wrong guesses kill the code even for the right one that follows; no account is made
- **the attacker re-registers the victim's address with their own password: the victim's code and the victim's
  browser (its old ticket) cannot create the account, the attacker with their own ticket cannot without the code, and
  the victim registering again replaces the attacker's row** (plan T19)
- **register answers the same for an address that has an account and one that does not** (status, body, cookies and
  mails queued), and so do verify and resend; the owner of the known address is mailed a notice
- a resend with the ticket sends a new code and kills the old one; without it nothing is sent and the live code is
  untouched; for an unknown address nothing is sent; always `202`
- a login resend sends only to an unverified account; always `202`
- the `429`s of the per-email and cooldown limits carry `Retry-After` and spend nothing when validation fails
- two sign-ups for aliases of one inbox make one account; an alias of an existing account is the known case
- a disposable domain is refused on the email field, a school address on the blocklist is not
- a verified account signs in with no code; an unverified one with the right password is mailed a code and told to enter
  it, with no cookies; a wrong password is a plain 401 and sends nothing; entering the code verifies it and signs in;
  an alias of the address finds the account
- the throwaway stack's outbox endpoint is a 404 unless the outbox backend is on, and then lists the mail to an address
"""

import pytest
from rest_framework.test import APIClient
from rest_framework.throttling import SimpleRateThrottle

from accounts.models import OutboundMail, PendingSignup, User, VerificationCode

pytestmark = pytest.mark.django_db

PASSWORD = "correct-horse-battery-staple"
ATTACKER_PASSWORD = "attackers-own-password-9"
INVALID = {"detail": "That code didn't work. Check it, or ask for a new one.", "code": "invalid_code"}


@pytest.fixture
def loose_limits(monkeypatch):
    """The code limits are tested on their own below; here a second register in the same minute must not be refused."""
    for scope in ("auth_code_cooldown", "auth_code_send_email", "auth_code_send_ip", "auth_code_check_email"):
        monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, scope, "1000/min")


def live_code(email, purpose="signup"):
    return VerificationCode.objects.get(email_canonical=email, purpose=purpose, consumed_at=None, invalidated_at=None)


# --- one answer for every failed check ---


def test_every_kind_of_failed_check_gives_the_identical_answer(signup, new_browser, loose_limits):
    signup.register(email="ada.new@example.com")  # a live code and this browser's ticket
    good = signup.code("ada.new@example.com")
    bad = "000000" if good != "000000" else "111111"
    stranger = new_browser()  # a browser with no ticket

    replies = {
        "wrong code": signup.verify("ada.new@example.com", bad),
        "no ticket": stranger.verify("ada.new@example.com", good),
        "never asked": signup.verify("nobody@example.com", "123456"),
    }
    signup.client.cookies["lc_signup"] = "forged-ticket"
    replies["forged ticket"] = signup.verify("ada.new@example.com", good)
    del signup.client.cookies["lc_signup"]
    replies["no cookie"] = signup.verify("ada.new@example.com", good)
    replies["unparseable"] = signup.client.post("/api/auth/verify", {"email": "nope"}, format="json")
    replies["bad purpose"] = signup.client.post(
        "/api/auth/verify", {"email": "ada.new@example.com", "code": good, "purpose": "reset"}, format="json"
    )

    for name, reply in replies.items():
        assert reply.status_code == 400 and reply.json() == INVALID, name
        assert not any(cookie in reply.cookies for cookie in ("lc_access", "lc_refresh", "lc_session")), name
    assert not User.objects.exists()


def test_a_used_an_expired_and_a_killed_code_give_the_same_answer_too(signup, loose_limits):
    signup.register(email="ada.new@example.com")
    code = signup.code("ada.new@example.com")
    assert signup.verify("ada.new@example.com", code).status_code == 200
    used = signup.verify("ada.new@example.com", code)  # the pending row and the code are spent

    signup.register(email="grace.new@example.com")
    VerificationCode.objects.filter(email_canonical="grace.new@example.com").update(expires_at="2000-01-01T00:00:00Z")
    expired = signup.verify("grace.new@example.com")

    signup.register(email="hedy.new@example.com")
    killed_code = signup.code("hedy.new@example.com")
    for _ in range(5):
        signup.verify("hedy.new@example.com", "000000" if killed_code != "000000" else "111111")
    killed = signup.verify("hedy.new@example.com", killed_code)

    assert [r.status_code for r in (used, expired, killed)] == [400, 400, 400]
    assert used.json() == expired.json() == killed.json() == INVALID


# --- the right code ---


def test_the_ticket_is_spent_with_the_account_and_cannot_be_used_again(signup, loose_limits):
    signup.register(email="ada.new@example.com")
    code = signup.code("ada.new@example.com")

    first = signup.verify("ada.new@example.com", code)
    again = signup.verify("ada.new@example.com", code)

    assert first.status_code == 200 and again.status_code == 400
    assert User.objects.filter(email_canonical="ada.new@example.com").count() == 1
    assert User.objects.get(email_canonical="ada.new@example.com").last_login is not None
    assert not PendingSignup.objects.exists()


def test_five_wrong_guesses_kill_the_code_even_for_the_right_one_after_them(signup):
    signup.register(email="ada.new@example.com")
    right = signup.code("ada.new@example.com")

    for _ in range(5):
        assert signup.verify("ada.new@example.com", "000000" if right != "000000" else "111111").status_code == 400
    late = signup.verify("ada.new@example.com", right)

    assert late.status_code == 400 and not User.objects.exists()


# --- the attacker who registers the victim's address (T19) ---


def test_an_attacker_who_re_registers_the_victims_address_cannot_plant_their_password(new_browser, loose_limits):
    victim, attacker = new_browser(), new_browser()
    victim.register(email="victim@example.com")  # the victim's own sign-up: their ticket, a code in their inbox
    victim_code = victim.code("victim@example.com")

    attacker.register(email="victim@example.com", name="Mallory", password=ATTACKER_PASSWORD)  # replaces the row
    code_in_victims_inbox = attacker.code("victim@example.com")  # the live code went to the victim's inbox

    # the victim types what is in their inbox (the live code), but their browser holds the old ticket
    for code in (victim_code, code_in_victims_inbox):
        assert victim.verify("victim@example.com", code).status_code == 400
    # the attacker holds the new ticket but has not got the code (the test reads it only to prove the next step)
    assert attacker.verify("victim@example.com", "000000").status_code == 400
    assert not User.objects.filter(email_canonical="victim@example.com").exists()  # nobody got an account

    # the victim registers again: that replaces the attacker's row, and the victim's own ticket and code work
    victim.register(email="victim@example.com", password=PASSWORD)
    assert victim.verify("victim@example.com").status_code == 200
    account = User.objects.get(email_canonical="victim@example.com")
    assert account.check_password(PASSWORD) and not account.check_password(ATTACKER_PASSWORD)
    assert account.name == "Grace Hopper"  # the victim's details, not Mallory's


def test_the_attacker_cannot_finish_the_victims_sign_up_without_the_code_and_the_victim_cannot_with_a_dead_ticket(
    new_browser, loose_limits
):
    victim, attacker = new_browser(), new_browser()
    victim.register(email="victim@example.com")
    attacker.register(email="victim@example.com", password=ATTACKER_PASSWORD)
    live = attacker.code("victim@example.com")

    # the live code works only with the ticket of the live row: the attacker's, but they cannot read the victim's inbox
    assert victim.verify("victim@example.com", live).status_code == 400  # the right code, the wrong browser
    assert not User.objects.exists()
    assert (
        attacker.verify("victim@example.com", live).status_code == 200
    )  # (only the inbox owner could have supplied it)


def test_a_stranger_who_sends_resends_cannot_cancel_the_live_code(new_browser, loose_limits, mailbox):
    victim, stranger = new_browser(), new_browser()
    victim.register(email="victim@example.com")
    code = victim.code("victim@example.com")
    mails = len(mailbox.messages)

    reply = stranger.resend("victim@example.com")  # no ticket

    assert reply.status_code == 202 and len(mailbox.messages) == mails  # nothing was sent
    assert victim.verify("victim@example.com", code).status_code == 200  # the live code was not cancelled


# --- the same reply for known and unknown ---


def test_register_answers_the_same_for_an_address_with_an_account_and_one_without(signup, user, mailbox, loose_limits):
    unknown = signup.register(email="newcomer@example.com")
    queued_unknown = OutboundMail.objects.count()
    known = signup.register(email=user.email)
    queued_known = OutboundMail.objects.count() - queued_unknown

    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json() == {"status": "verification_required"}
    assert set(known.cookies) == set(unknown.cookies) == {"lc_signup"}  # a ticket either way
    assert known.cookies["lc_signup"]["max-age"] == unknown.cookies["lc_signup"]["max-age"]
    assert known.cookies["lc_signup"]["httponly"] == unknown.cookies["lc_signup"]["httponly"]
    assert queued_known == queued_unknown == 1  # one mail each: a code, or a notice to the owner
    assert [m.kind for m in mailbox.to(user.email)] == ["owner_notice"]
    assert [m.kind for m in mailbox.to("newcomer@example.com")] == ["signup_code"]


def test_a_known_address_gets_no_pending_row_and_its_ticket_matches_nothing(signup, user, loose_limits):
    signup.register(email=user.email)

    assert not PendingSignup.objects.exists() and not VerificationCode.objects.exists()
    assert signup.verify(user.email, "123456").status_code == 400
    assert signup.resend(user.email).status_code == 202


def test_refusals_do_not_depend_on_whether_the_address_has_an_account(signup, user, loose_limits):
    weak = {"password": "12345"}
    known, unknown = signup.register(email=user.email, **weak), signup.register(email="new@example.com", **weak)
    no_terms_known = signup.register(email=user.email, accept_terms=False)
    no_terms_unknown = signup.register(email="new@example.com", accept_terms=False)

    assert known.status_code == unknown.status_code == 400 and known.json() == unknown.json()
    assert no_terms_known.json() == no_terms_unknown.json()


def test_resend_and_verify_say_the_same_for_known_and_unknown_addresses(signup, user, loose_limits):
    for email in (user.email, "nobody@example.com"):
        assert signup.resend(email).status_code == 202
        assert signup.resend(email).json() == {"status": "sent"}
        assert signup.verify(email, "123456").json() == INVALID


# --- resend ---


def test_a_resend_with_the_ticket_sends_a_new_code_and_kills_the_old_one(signup, loose_limits, mailbox):
    signup.register(email="ada.new@example.com")
    old = signup.code("ada.new@example.com")

    reply = signup.resend("ada.new@example.com")
    new = signup.code("ada.new@example.com")

    assert reply.status_code == 202 and reply.json() == {"status": "sent"}
    assert len(mailbox.to("ada.new@example.com", "signup_code")) == 2
    assert VerificationCode.objects.filter(email_canonical="ada.new@example.com").count() == 2
    assert live_code("ada.new@example.com").code_hash != ""
    if old != new:  # (a one-in-a-million repeat would make the old code the new one)
        assert signup.verify("ada.new@example.com", old).status_code == 400
    assert signup.verify("ada.new@example.com", new).status_code == 200


def test_a_login_resend_goes_only_to_an_unverified_account(signup, user, mailbox, loose_limits):
    unverified = User.objects.create_user("unproved@example.com", password=PASSWORD, name="Unproved")

    replies = [signup.resend(email, "login") for email in (unverified.email, user.email, "nobody@example.com")]

    assert [r.status_code for r in replies] == [202, 202, 202]
    assert [m.kind for m in mailbox.messages] == ["login_code"]
    assert mailbox.messages[0].to == unverified.email


# --- the limits ---


def test_the_cooldown_refuses_a_second_code_within_a_minute_with_retry_after(signup):
    signup.register(email="ada.new@example.com")

    again = signup.resend("ada.new@example.com")

    assert again.status_code == 429 and again.json()["code"] == "throttled"
    assert 0 < int(again["Retry-After"]) <= 60


def test_a_request_that_fails_validation_spends_none_of_the_send_limits(signup):
    assert signup.register(email="ada.new@example.com", password="12345").status_code == 400
    assert signup.register(email="ada.new@example.com", accept_terms=False).status_code == 400

    assert signup.register(email="ada.new@example.com").status_code == 202  # not refused for a cooldown


def test_the_limits_count_by_the_canonical_email_so_an_alias_shares_the_budget(signup):
    assert signup.register(email="a.b+one@gmail.com").status_code == 202

    assert signup.register(email="ab@gmail.com").status_code == 429


def test_the_check_limit_per_email_stops_guessing_with_a_429(signup, monkeypatch):
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "auth_code_check_email", "3/hour")
    signup.register(email="ada.new@example.com")

    answers = [signup.verify("ada.new@example.com", "000000").status_code for _ in range(5)]

    assert answers == [400, 400, 400, 429, 429]


def test_an_unknown_address_is_limited_exactly_like_a_known_one(signup, user, monkeypatch):
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "auth_code_check_email", "2/hour")

    known = [signup.verify(user.email, "000000").status_code for _ in range(3)]
    unknown = [signup.verify("nobody@example.com", "000000").status_code for _ in range(3)]

    assert known == unknown == [400, 400, 429]


# --- aliases and the policy ---


def test_two_sign_ups_for_aliases_of_one_inbox_make_one_account(signup, loose_limits):
    signup.register(email="Ada.Lovelace+one@gmail.com")
    signup.register(email="adalovelace@googlemail.com")  # the same inbox, the later one wins
    assert PendingSignup.objects.count() == 1

    assert signup.verify("adalovelace@googlemail.com").status_code == 200

    assert User.objects.count() == 1
    assert User.objects.get().email == "adalovelace@googlemail.com"  # as the account was finished, typed


def test_an_alias_of_an_existing_account_is_the_known_case(signup, user, mailbox, loose_limits):
    reply = signup.register(email="ADA+maths@example.com")  # `+tag` is dropped for every domain

    assert reply.status_code == 202 and not PendingSignup.objects.exists()
    assert [m.kind for m in mailbox.to(user.email)] == ["owner_notice"]


def test_a_disposable_domain_is_refused_on_the_email_field_and_a_real_one_is_not(signup):
    refused = signup.register(email="x@mailinator.com")

    assert refused.status_code == 400
    assert "Temporary email addresses" in refused.json()["fields"]["email"][0]
    assert not PendingSignup.objects.exists() and "lc_signup" not in refused.cookies
    assert signup.register(email="x@gmail.com").status_code == 202


# --- sign-in for an account that never proved its email ---


def test_a_verified_account_signs_in_with_no_code(signup, user):
    assert signup.login(user.email, PASSWORD).status_code == 200


def test_an_unverified_account_with_the_right_password_is_mailed_a_code_and_not_signed_in(signup, mailbox):
    User.objects.create_user("unproved@example.com", password=PASSWORD, name="Unproved")

    reply = signup.login("unproved@example.com")

    assert reply.status_code == 403 and reply.json()["code"] == "verification_required"
    assert not any(cookie in reply.cookies for cookie in ("lc_access", "lc_refresh", "lc_session"))
    assert [m.kind for m in mailbox.to("unproved@example.com")] == ["login_code"]
    assert live_code("unproved@example.com", "login").user.email == "unproved@example.com"


def test_a_wrong_password_for_an_unverified_account_is_a_plain_401_and_sends_nothing(signup, mailbox):
    User.objects.create_user("unproved@example.com", password=PASSWORD, name="Unproved")

    reply = signup.login("unproved@example.com", "wrong-password")

    assert reply.status_code == 401 and reply.json()["code"] == "invalid_credentials"
    assert mailbox.messages == []


def test_entering_the_login_code_verifies_the_account_and_signs_in(signup):
    account = User.objects.create_user("unproved@example.com", password=PASSWORD, name="Unproved")
    signup.login("unproved@example.com")

    reply = signup.verify("unproved@example.com", purpose="login")

    assert reply.status_code == 200 and reply.cookies["lc_access"]["httponly"]
    account.refresh_from_db()
    assert account.is_email_verified and account.email_verification_source == "code"
    assert signup.login("unproved@example.com").status_code == 200  # no code the next time


def test_the_login_code_works_only_for_an_unverified_account_and_not_as_a_sign_up_code(signup, user):
    signup.login("unproved@example.com")  # no such account: nothing is sent
    account = User.objects.create_user("unproved@example.com", password=PASSWORD, name="Unproved")
    signup.login("unproved@example.com")
    code = signup.code("unproved@example.com", "login_code")

    wrong_purpose = signup.verify("unproved@example.com", code, purpose="signup")
    verified_account = signup.verify(user.email, "123456", purpose="login")

    assert wrong_purpose.status_code == 400 and verified_account.status_code == 400
    account.refresh_from_db()
    assert not account.is_email_verified


def test_an_alias_of_the_address_signs_in_to_the_same_account(signup, user):
    reply = signup.login("ADA+x@Example.com")

    assert reply.status_code == 200 and reply.json()["user"]["id"] == str(user.id)


def test_a_login_that_cannot_send_a_code_still_answers_403_and_sends_nothing(signup, mailbox, monkeypatch):
    User.objects.create_user("unproved@example.com", password=PASSWORD, name="Unproved")
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "auth_code_send_email", "1/hour")
    signup.login("unproved@example.com")

    again = signup.login("unproved@example.com")

    assert again.status_code == 403 and again.json()["code"] == "verification_required"
    assert len(mailbox.messages) == 1


# --- the throwaway stack's outbox ---


def test_the_outbox_endpoint_is_a_404_unless_the_outbox_backend_is_on(api_client):
    OutboundMail.objects.create(
        kind="signup_code", to_email="ada@example.com", backend="outbox", body_text="Code 123456"
    )

    assert api_client.get("/api/dev/outbox", {"email": "ada@example.com"}).status_code == 404


def test_the_outbox_endpoint_lists_the_mail_to_an_address_when_the_outbox_is_on(api_client, settings):
    settings.DEBUG, settings.MAIL_ALLOW_OUTBOX, settings.MAIL_BACKEND = True, True, "outbox"
    OutboundMail.objects.create(
        kind="signup_code", to_email="Ada@Example.com", backend="outbox", body_text="Code 123456"
    )
    OutboundMail.objects.create(
        kind="signup_code", to_email="grace@example.com", backend="outbox", body_text="Code 999999"
    )

    reply = api_client.get("/api/dev/outbox", {"email": "ada@example.com"})

    assert reply.status_code == 200
    assert [(m["kind"], m["text"]) for m in reply.json()["messages"]] == [("signup_code", "Code 123456")]


def test_the_outbox_endpoint_is_a_404_when_debug_is_off_even_with_the_switches_on(api_client, settings):
    settings.DEBUG, settings.MAIL_ALLOW_OUTBOX, settings.MAIL_BACKEND = False, True, "outbox"

    assert api_client.get("/api/dev/outbox", {"email": "ada@example.com"}).status_code == 404


# --- CSRF ---


def test_the_code_endpoints_need_the_csrf_header(django_capture_on_commit_callbacks):
    client = APIClient(enforce_csrf_checks=True)
    body = {"email": "ada@example.com", "code": "123456", "purpose": "signup"}

    assert client.post("/api/auth/verify", body, format="json").status_code == 403
    assert (
        client.post(
            "/api/auth/verify/resend", {"email": "ada@example.com", "purpose": "signup"}, format="json"
        ).status_code
        == 403
    )
    assert client.post("/api/auth/register", {}, format="json").status_code == 403
