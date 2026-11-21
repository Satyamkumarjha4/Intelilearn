"""Unit under test: `live.usage_payloads.UsagePayload`, the helper the live usage test uses to write down what a
provider's reply said about tokens. Offline: no model is called.

Why: the cost code reads `usage_metadata`; if a provider names a field differently or leaves the thinking tokens out,
the cost is wrong on every call. The helper must show exactly what came back and list what the cost code cannot read.

Use cases:
- the payload holds LangChain's usage, the provider's own usage block and the names of the response metadata keys
- a reply with integer input and output tokens has no findings
- a missing or non-numeric count is a finding, and so is thinking that was asked for but not reported
- the printed line names the provider and model and is plain JSON
"""

import json
from types import SimpleNamespace

from live.usage_payloads import UsagePayload


def message(**usage):
    """A reply as far as the helper reads it (a real `AIMessage` refuses a usage with counts missing)."""
    return SimpleNamespace(usage_metadata=usage, response_metadata={"token_usage": {"completion_tokens": 7}})


def test_the_payload_holds_both_usages_and_the_metadata_keys():
    payload = UsagePayload.of(message(input_tokens=9, output_tokens=7, total_tokens=16))

    assert payload["usage_metadata"] == {"input_tokens": 9, "output_tokens": 7, "total_tokens": 16}
    assert payload["provider_usage"] == {"completion_tokens": 7}
    assert payload["response_metadata_keys"] == ["token_usage"]


def test_a_reply_with_integer_input_and_output_tokens_has_no_findings():
    payload = UsagePayload.of(message(input_tokens=9, output_tokens=7, total_tokens=16))

    assert UsagePayload.findings(payload, thinking_asked=False) == []


def test_a_missing_count_and_unreported_thinking_are_findings():
    payload = UsagePayload.of(message(input_tokens=9))

    assert UsagePayload.findings(payload, thinking_asked=True) == [
        "output_tokens is missing or not a number",
        "thinking was asked for but output_token_details.reasoning is not reported",
    ]


def test_reported_thinking_is_not_a_finding():
    usage = dict(input_tokens=9, output_tokens=7, total_tokens=16, output_token_details={"reasoning": 3})

    assert UsagePayload.findings(UsagePayload.of(message(**usage)), thinking_asked=True) == []


def test_the_printed_line_names_the_model_and_is_plain_json():
    line = UsagePayload.text("groq", "openai/gpt-oss-20b", UsagePayload.of(message(input_tokens=1, output_tokens=2)))

    assert line.startswith("USAGE groq/openai/gpt-oss-20b: ")
    assert json.loads(line.split(": ", 1)[1])["usage_metadata"]["output_tokens"] == 2
