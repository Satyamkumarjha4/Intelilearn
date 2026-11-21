"""Unit under test: `core.audit.spend` (`AuditSpend`) and `manage.py audit_spend`: what a live audit has spent on
models, against `LIVE_MAX_COST_USD`.

Why: a live audit run calls real models on a paid key. The cap is a promise to the person paying, and the only record
of spend is the call log of the throwaway stack. The command is how an audit stage asks "may I make another call?",
so it must be exact about the total, say when the log cannot price a call (an unknown figure is not zero), and exit
non-zero over the cap so a script can stop.

Use cases:
- the report sums the cost, input and output tokens and counts the calls
- calls the log could not price are counted apart, and the report says the total may be low
- a total at the cap is within budget, one cent over is over it
- the cap comes from LIVE_MAX_COST_USD (2.00 when it is not set), and a bad value is refused
- the command prints the figures and exits with an error (CommandError) when over the cap
- the command with no calls says $0.00 and is within budget
"""

from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from core.audit.spend import AuditSpend, BadCap
from llm_registry.models import ModelCall

pytestmark = pytest.mark.django_db


def call(cost, input_tokens=100, output_tokens=50, **fields):
    return ModelCall.objects.create(
        node_key="diagnostic.generate",
        provider_key="gemini",
        model_name="gemini-flash",
        attempt=1,
        fallback_index=0,
        latency_ms=10,
        status="ok",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost,
        **fields,
    )


class TestReport:
    def test_it_sums_the_cost_and_the_tokens_and_counts_the_calls(self):
        call(Decimal("0.010000"))
        call(Decimal("0.025000"), input_tokens=300, output_tokens=70)

        report = AuditSpend(Decimal("2")).report()

        assert report.calls == 2 and report.cost_usd == Decimal("0.035000")
        assert (report.input_tokens, report.output_tokens) == (400, 120)
        assert report.unpriced == 0 and report.over is False

    def test_calls_the_log_could_not_price_are_counted_apart(self):
        call(Decimal("0.010000"))
        call(None)

        report = AuditSpend(Decimal("2")).report()

        assert report.unpriced == 1 and report.cost_usd == Decimal("0.010000")

    def test_a_total_at_the_cap_is_within_budget_and_one_cent_over_is_over(self):
        call(Decimal("2.000000"))
        assert AuditSpend(Decimal("2")).report().over is False

        call(Decimal("0.010000"))
        assert AuditSpend(Decimal("2")).report().over is True

    def test_no_calls_is_zero_and_within_budget(self):
        report = AuditSpend(Decimal("2")).report()

        assert report.calls == 0 and report.cost_usd == Decimal("0") and not report.over


class TestCap:
    def test_it_comes_from_the_environment_or_is_two_dollars(self, monkeypatch):
        monkeypatch.delenv("LIVE_MAX_COST_USD", raising=False)
        assert AuditSpend.from_environment().cap == Decimal("2.00")

        monkeypatch.setenv("LIVE_MAX_COST_USD", "5.5")
        assert AuditSpend.from_environment().cap == Decimal("5.5")

    @pytest.mark.parametrize("bad", ["lots", "-1", ""])
    def test_a_bad_value_is_refused(self, monkeypatch, bad):
        monkeypatch.setenv("LIVE_MAX_COST_USD", bad)

        with pytest.raises(BadCap):
            AuditSpend.from_environment()


class TestCommand:
    def test_it_prints_the_figures_within_budget(self, monkeypatch):
        monkeypatch.setenv("LIVE_MAX_COST_USD", "2")
        call(Decimal("0.5"))
        out = StringIO()

        call_command("audit_spend", stdout=out)

        text = out.getvalue()
        assert "$0.50" in text and "of $2.00" in text and "within budget" in text

    def test_over_the_cap_it_stops_with_an_error(self, monkeypatch):
        monkeypatch.setenv("LIVE_MAX_COST_USD", "1")
        call(Decimal("1.5"))

        with pytest.raises(CommandError, match="over budget"):
            call_command("audit_spend", stdout=StringIO())

    def test_a_bad_cap_is_a_command_error(self, monkeypatch):
        monkeypatch.setenv("LIVE_MAX_COST_USD", "lots")

        with pytest.raises(CommandError, match="LIVE_MAX_COST_USD"):
            call_command("audit_spend", stdout=StringIO())
