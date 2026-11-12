"""Unit under test: `manage.py require_reverification` and `manage.py refresh_disposable_domains`.

Why: before launch the dev accounts that never proved an email must be asked for a code at their next sign-in without
losing their credits and without locking staff out, and the list of disposable domains must be refreshed without ever
writing a bad file. Both are run by a person once, so what they print is what the person trusts.

Use cases:
- `require_reverification` sets legacy accounts back to unverified and says how many; their credits stay and the next
  password sign-in asks for a code
- staff accounts are left alone by default and with `--keep-staff`, and included with `--include-staff`
- accounts proved by a code or by Google, operator accounts and erased accounts are left alone
- `--dry-run` says what would change and changes nothing
- `refresh_disposable_domains` reports the count and the commit, names a dropped real provider, and turns a refused
  list into a command error that leaves the file as it was
"""

from io import StringIO

import httpx
import pytest
from django.core.management import CommandError, call_command

from accounts.emailrules.disposable import DisposableDomains
from accounts.management.commands import refresh_disposable_domains
from accounts.models import User
from credits.earning.signup import SignupGrant
from credits.models import CreditBucket

pytestmark = pytest.mark.django_db

PASSWORD = "correct-horse-battery-staple"


def run(command, *args):
    out = StringIO()
    call_command(command, *args, stdout=out)
    return out.getvalue()


def legacy(email, **extra):
    return User.objects.create_user( email, password=PASSWORD, name="Old",
email_verified_at="2026-01-01T00:00:00Z", email_verification_source="legacy", **extra, )  # fmt: skip


def source_of(user):
    user.refresh_from_db()
    return user.email_verification_source


class TestRequireReverification:
    def test_legacy_accounts_become_unverified_and_keep_their_credits(self, signup):
        account = legacy("old@example.com")
        SignupGrant().on_account_ready(account)

        out = run("require_reverification")

        account.refresh_from_db()
        assert "1 legacy accounts will ask for a code" in out
        assert not account.is_email_verified and account.email_verification_source == ""
        assert CreditBucket.objects.get(user=account).amount_remaining == 30  # the credits stay
        assert signup.login("old@example.com").status_code == 403  # and the next password sign-in asks for a code

    @pytest.mark.parametrize("flags", [(), ("--keep-staff",)])
    def test_staff_are_left_alone_by_default_and_with_keep_staff(self, flags):
        boss = legacy("boss@example.com", is_staff=True)
        root = legacy("root@example.com", is_superuser=True)

        run("require_reverification", *flags)

        assert source_of(boss) == source_of(root) == "legacy"

    def test_include_staff_asks_staff_for_a_code_too(self):
        boss = legacy("boss@example.com", is_staff=True)

        run("require_reverification", "--include-staff")

        assert source_of(boss) == ""

    def test_accounts_proved_by_a_code_or_google_operator_accounts_and_erased_ones_are_left_alone(self, user):
        proved = User.objects.create_user(
            "proved@example.com", password=PASSWORD, name="P", email_verified_at="2026-01-01T00:00:00Z",
            email_verification_source="code",
        )  # fmt: skip
        google = User.objects.create_user(
            "g@example.com", password=PASSWORD, name="G", email_verified_at="2026-01-01T00:00:00Z",
            email_verification_source="google",
        )  # fmt: skip
        erased = legacy("erased@example.com")
        User.objects.filter(pk=erased.pk).update(deleted_at="2026-02-01T00:00:00Z")

        run("require_reverification", "--include-staff")

        assert [source_of(u) for u in (user, proved, google, erased)] == ["operator", "code", "google", "legacy"]

    def test_a_dry_run_says_what_would_change_and_changes_nothing(self):
        account = legacy("old@example.com")

        out = run("require_reverification", "--dry-run")

        assert "Dry run: would make 1 legacy accounts ask for a code" in out
        assert source_of(account) == "legacy"


class TestRefreshDisposableDomains:
    @staticmethod
    def serve(monkeypatch, tmp_path, names, status=200):
        path = tmp_path / "list.txt"
        path.write_text("# old\nold.example\n", encoding="utf-8")
        commit = {"sha": "b" * 40, "commit": {"committer": {"date": "2026-11-08T18:39:02Z"}}}

        def handler(request):
            if request.url.host == "raw.githubusercontent.com":
                return httpx.Response(status, text="\n".join(names))
            return httpx.Response(200, json=[commit])

        monkeypatch.setattr(DisposableDomains, "BLOCKLIST", path)
        monkeypatch.setattr(
            refresh_disposable_domains.Command,
            "client",
            lambda self: httpx.Client(transport=httpx.MockTransport(handler)),
        )
        return path

    def test_it_reports_the_count_and_the_commit_and_names_a_dropped_provider(self, monkeypatch, tmp_path):
        names = [f"junk{n}.example" for n in range(1100)] + ["sify.com"]
        path = self.serve(monkeypatch, tmp_path, names)

        out = run("refresh_disposable_domains")

        assert "1100 domains, source commit " + "b" * 40 in out
        assert "Dropped real providers the list held: sify.com" in out
        assert "sify.com" not in path.read_text(encoding="utf-8").split("\n# ")[-1].split("\n", 1)[-1]

    def test_a_refused_list_is_a_command_error_and_the_file_is_left_alone(self, monkeypatch, tmp_path):
        path = self.serve(monkeypatch, tmp_path, ["one.example"])

        with pytest.raises(CommandError, match="fewer than"):
            run("refresh_disposable_domains")

        assert path.read_text(encoding="utf-8") == "# old\nold.example\n"
