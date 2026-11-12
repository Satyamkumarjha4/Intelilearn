"""Unit under test: `manage.py probe_forwarded_header`, the operator's check that a visitor cannot choose the address
the per-address limits count (launch checklist 12.7, item 8).

Why: after a deploy the edge proxy is the only thing that can stop a client from picking its own address, and the only
way to know it does is to try. The command must say what it found and exit non-zero (a `CommandError`) when it can be
fooled, so a deploy script can stop on it.

Use cases:
- when the front door cannot be fooled the command prints each case as ok and ends well
- when it can be fooled the command prints FAIL for that case and raises a CommandError
"""

import io

import pytest
from django.core.management import CommandError, call_command

from core.management.commands import probe_forwarded_header
from core.proxy_probe import ProbeFinding, ProbeReport


class StubProbe:
    report: ProbeReport

    def __init__(self, client):
        pass

    def run(self, url):
        self.url = url
        return type(self).report


def _finding(passed):
    counted = None if passed else "198.51.100.5"
    return ProbeFinding("a single forged entry", "198.51.100.5", "198.51.100.5", counted, passed, "why")


def test_a_front_door_that_cannot_be_fooled_ends_well(monkeypatch):
    StubProbe.report = ProbeReport((_finding(True),))
    monkeypatch.setattr(probe_forwarded_header, "ForwardedHeaderProbe", StubProbe)
    out = io.StringIO()

    call_command("probe_forwarded_header", "--url", "https://site.test", stdout=out)

    assert "ok   a single forged entry" in out.getvalue()
    assert "was not counted" in out.getvalue()


def test_a_front_door_that_can_be_fooled_fails_loudly(monkeypatch):
    StubProbe.report = ProbeReport((_finding(False),))
    monkeypatch.setattr(probe_forwarded_header, "ForwardedHeaderProbe", StubProbe)
    out = io.StringIO()

    with pytest.raises(CommandError, match="choose the address"):
        call_command("probe_forwarded_header", stdout=out)

    assert "FAIL a single forged entry" in out.getvalue()
