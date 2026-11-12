"""Unit under test: `accounts.emailrules.disposable.DisposableDomains` and the vendored files it reads
(`data/disposable_email_domains.txt`, `data/school_allowlist.txt`).

Why: a verified email only stops farming if throwaway inboxes are refused, but a blocklist maintained by strangers is
also a way to lock real people out: one mistaken line and every Gmail user is refused. So the matching rules are
tested as a table, the allow-list of ours always wins, and **the shipped snapshot is held to a test that it never
contains a major real provider** (the product owner's rule, D8). That test is shown failing against a snapshot with
`gmail.com` added.

Use cases:
- a listed domain is blocked, and so is any subdomain of it; an unlisted one, and one that only ends the same way, is
  not
- the allow-list always wins, for a name and for a whole suffix (`ac.in`, `edu`)
- list files are read one name per line, with `#` comments and blank lines ignored, lowercase
- the shipped snapshot has a header that names its source, commit and fetch date
- **the shipped snapshot never contains a major real provider** (the list is in this test, one per line) and the
  names the code protects include every one of them
- the shipped snapshot blocks well-known throwaway services and lets a school address through
"""

import re

import pytest

from accounts.emailrules.disposable import DisposableDomains
from accounts.emailrules.providers import MajorProviders

#: Real mail providers, one per line. The test fails if one is in the snapshot, and if `MajorProviders` (which the
#: refresh uses to drop them) does not know it.
MAJOR_PROVIDERS = """
gmail.com
googlemail.com
outlook.com
outlook.in
hotmail.com
hotmail.co.in
hotmail.co.uk
live.com
live.in
msn.com
yahoo.com
yahoo.co.in
yahoo.in
yahoo.co.uk
ymail.com
icloud.com
me.com
mac.com
aol.com
proton.me
protonmail.com
zoho.com
rediffmail.com
rediff.com
sify.com
in.com
bsnl.in
vsnl.com
vsnl.net
""".split()


def test_a_listed_domain_and_its_subdomains_are_blocked_and_nothing_else():
    domains = DisposableDomains({"mailinator.com", "10minutemail.net"})

    assert domains.blocks("mailinator.com")
    assert domains.blocks("MAILINATOR.com")
    assert domains.blocks("x.y.mailinator.com")
    assert not domains.blocks("notmailinator.com")  # only the name itself and its subdomains
    assert not domains.blocks("mailinator.com.example.org")
    assert not domains.blocks("example.com")


@pytest.mark.parametrize("domain", ["school.ac.in", "mail.school.ac.in", "college.edu", "x.college.edu", "uni.ac.uk"])
def test_the_allow_list_always_wins_whole_suffixes_included(domain):
    domains = DisposableDomains({domain, "ac.in", "edu", "other.com"}, allowed={"ac.in", "edu", "ac.uk"})

    assert not domains.blocks(domain)


def test_an_allowed_name_beats_a_blocked_parent_but_a_blocked_name_beside_it_stays_blocked():
    domains = DisposableDomains({"example.net", "bad.example.net"}, allowed={"good.example.net"})

    assert not domains.blocks("good.example.net")
    assert not domains.blocks("mail.good.example.net")
    assert domains.blocks("bad.example.net")


def test_list_files_are_one_name_per_line_with_comments_and_blank_lines_ignored(tmp_path):
    path = tmp_path / "list.txt"
    path.write_text("# a header\n\nMailinator.com  \nfoo.test # trailing note\n   \n#other.test\n", encoding="utf-8")

    assert DisposableDomains.read(path) == {"mailinator.com", "foo.test"}


def test_the_shipped_snapshot_names_its_source_commit_and_date():
    header = [
        line for line in DisposableDomains.BLOCKLIST.read_text(encoding="utf-8").splitlines() if line.startswith("#")
    ]
    text = "\n".join(header)

    assert "disposable-email-domains" in text
    assert re.search(r"Source commit: [0-9a-f]{40} \(\d{4}-\d{2}-\d{2}\)", text)
    assert re.search(r"Fetched: \d{4}-\d{2}-\d{2}", text)


@pytest.mark.parametrize("domain", MAJOR_PROVIDERS)
def test_the_shipped_snapshot_never_contains_a_major_real_provider(domain):
    snapshot = DisposableDomains.read(DisposableDomains.BLOCKLIST)

    assert domain not in snapshot, f"{domain} is a real mail provider: refusing it would lock real people out"
    assert not DisposableDomains.default().blocks(domain)
    assert domain in MajorProviders.DOMAINS, f"{domain} must be on the never-block list the refresh uses"


def test_the_shipped_snapshot_blocks_known_throwaway_services_and_lets_a_school_through():
    domains = DisposableDomains.default()

    assert domains.blocks("mailinator.com")
    assert domains.blocks("sub.mailinator.com")
    assert not domains.blocks("student.example.ac.in")
    assert len(domains.blocked) > 5000  # a list this short would be a broken download
