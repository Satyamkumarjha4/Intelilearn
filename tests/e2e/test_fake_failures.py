"""Unit under test: `FailurePlan` (tests/e2e/fake_failures.py) and the control endpoints of the fake LLM server that
drive it.

Why: the audit has to see what the app does when a model misbehaves (a reply that is not JSON, a reply the validators
refuse, a timeout, a 429, a 401), and a real provider cannot be asked to fail on cue. The plan is how a test or an
auditor says "the next call for this schema fails like this", and it has to be exact: a rule that fires once too often
or too rarely makes the fallback and refund paths look wrong when they are not.

Use cases:
- a rule fires for the schema it names, as many times as it says, and then stops
- a rule for every schema ("*") fires for any schema
- a rule with times -1 fires on every call until it is reset
- a rule for one schema leaves the others alone, and the first matching rule is the one used
- reset forgets every rule
- a rule must name a mode the server knows; an unknown mode, a zero or negative count other than -1, or a non-number
  delay is refused with a message that lists the allowed modes
- the plan says what it holds and how many calls each schema has had, without a secret in it
- POST /_control/fail adds a rule, GET /_control/plan reads the plan, POST /_control/reset empties it, over HTTP
- a bad control request is a 400 with the reason, and an unknown control path is a 404
"""

import json
import urllib.error
import urllib.request

import pytest
from e2e.fake_failures import FailurePlan, FailureRule, UnknownFailure
from e2e.fake_llm_server import FakeLLMServer


class TestRules:
    def test_a_rule_fires_for_its_schema_as_many_times_as_it_says_then_stops(self):
        plan = FailurePlan()
        plan.add("rate_limit", schema="DiagnosticBundle", times=2)

        taken = [plan.take("DiagnosticBundle") for _ in range(3)]

        assert [rule.mode if rule else None for rule in taken] == ["rate_limit", "rate_limit", None]

    def test_a_rule_for_any_schema_fires_for_any_schema(self):
        plan = FailurePlan()
        plan.add("unauthorized")

        assert plan.take("QuizReview").mode == "unauthorized"
        assert plan.take("QuizReview") is None

    def test_a_rule_with_times_minus_one_fires_on_every_call_until_reset(self):
        plan = FailurePlan()
        plan.add("invalid_json", times=-1)

        assert all(plan.take("CheatSheet") is not None for _ in range(50))

        plan.reset()
        assert plan.take("CheatSheet") is None

    def test_a_rule_for_one_schema_leaves_the_others_alone_and_the_first_match_wins(self):
        plan = FailurePlan()
        plan.add("timeout", schema="PageContent")
        plan.add("rate_limit")

        assert plan.take("QuestionBatch").mode == "rate_limit"
        assert plan.take("PageContent").mode == "timeout"  # the earlier rule, though a later one also matches

    def test_reset_forgets_every_rule(self):
        plan = FailurePlan()
        plan.add("rate_limit", times=5)
        plan.add("timeout", schema="PageContent")

        plan.reset()

        assert plan.take("PageContent") is None and plan.snapshot()["rules"] == []


class TestRefusals:
    def test_an_unknown_mode_is_refused_and_the_message_lists_the_modes(self):
        with pytest.raises(UnknownFailure) as refused:
            FailurePlan().add("explode")

        assert "invalid_json" in str(refused.value) and "unauthorized" in str(refused.value)

    @pytest.mark.parametrize("times", [0, -2, 1.5, "two", True])
    def test_a_count_that_is_not_a_positive_number_or_minus_one_is_refused(self, times):
        with pytest.raises(UnknownFailure):
            FailurePlan().add("rate_limit", times=times)

    def test_a_delay_that_is_not_a_number_is_refused(self):
        with pytest.raises(UnknownFailure):
            FailurePlan().add("timeout", delay_s="long")


class TestSnapshot:
    def test_the_snapshot_lists_the_rules_and_counts_the_calls_each_schema_had(self):
        plan = FailurePlan()
        plan.add("rate_limit", schema="CheatSheet", times=2)

        plan.take("CheatSheet")
        plan.take("PracticeSheet")
        snapshot = plan.snapshot()

        assert snapshot["rules"] == [{"mode": "rate_limit", "schema": "CheatSheet", "times": 1, "delay_s": 0}]
        assert snapshot["calls"] == {"CheatSheet": 1, "PracticeSheet": 1}
        assert snapshot["failed"] == {"CheatSheet": 1}

    def test_a_rule_is_a_frozen_value(self):
        rule = FailureRule("rate_limit", "*", 1, 0)

        with pytest.raises(AttributeError):
            rule.mode = "timeout"


@pytest.fixture
def server():
    with FakeLLMServer() as running:
        yield running


def control(server, method: str, path: str, body: dict | None = None):
    base = server.base_url.removesuffix("/v1")
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(  # noqa: S310 (a loopback test server)
        f"{base}{path}", data=data, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request) as reply:  # noqa: S310
            return reply.status, json.loads(reply.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


class TestControlEndpoints:
    def test_a_rule_is_added_read_and_reset_over_http(self, server):
        status, _ = control(
            server, "POST", "/_control/fail", {"mode": "rate_limit", "schema": "CheatSheet", "times": 3}
        )
        assert status == 200

        status, plan = control(server, "GET", "/_control/plan")
        assert status == 200 and plan["rules"] == [
            {"mode": "rate_limit", "schema": "CheatSheet", "times": 3, "delay_s": 0}
        ]

        status, plan = control(server, "POST", "/_control/reset")
        assert status == 200 and plan["rules"] == []

    def test_a_bad_control_request_is_a_400_with_the_reason(self, server):
        status, body = control(server, "POST", "/_control/fail", {"mode": "explode"})

        assert status == 400 and "invalid_json" in body["error"]["message"]

    def test_a_control_request_that_is_not_json_is_a_400(self, server):
        base = server.base_url.removesuffix("/v1")
        request = urllib.request.Request(f"{base}/_control/fail", data=b"{nope", method="POST")  # noqa: S310
        with pytest.raises(urllib.error.HTTPError) as refused:
            urllib.request.urlopen(request)  # noqa: S310

        assert refused.value.code == 400

    def test_an_unknown_control_path_is_a_404(self, server):
        status, _ = control(server, "POST", "/_control/explode")

        assert status == 404
