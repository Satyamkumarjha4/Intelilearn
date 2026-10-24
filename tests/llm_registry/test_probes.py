"""Unit under test: `llm_registry.probes.ModelProber` and its CapabilityProbes, the admin's "Test model" and
`manage.py probe_models`: one small real call per capability a model claims.

Why: a wrongly ticked capability (say, vision on a text-only model) would only surface in the middle of a lesson. The
probes have to report each failure clearly, and must never crash the admin action.

Use cases:
- the generated test PNG is valid (size and every chunk CRC)
- every declared capability is probed, in order, and passes on a capable model
- a capability that doesn't work is reported with the reason; undeclared ones are not probed
- a client that can't be built is a failed "setup" result, not an exception
- only the probes given to the prober run
"""

import struct
import zlib

import pytest
from langchain_core.messages import AIMessage

from llm_registry.probes import ModelProber, VisionProbe

pytestmark = pytest.mark.django_db


def test_generated_png_is_valid():
    png = VisionProbe.solid_png((255, 0, 0), size=4)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    width, height = struct.unpack(">II", png[16:24])
    assert (width, height) == (4, 4)
    # every chunk's CRC must match
    offset = 8
    while offset < len(png):
        (length,) = struct.unpack(">I", png[offset : offset + 4])
        kind_and_data = png[offset + 4 : offset + 8 + length]
        (crc,) = struct.unpack(">I", png[offset + 8 + length : offset + 12 + length])
        assert zlib.crc32(kind_and_data) & 0xFFFFFFFF == crc
        offset += 12 + length


class ProbeChat:
    """Answers every probe; `tool_call=False` simulates a model that ignores tools."""

    def __init__(self, tool_call=True):
        self.tool_call = tool_call

    def invoke(self, messages):
        return AIMessage(content="pong")

    def with_structured_output(self, schema, method=None, include_raw=False):
        class Runnable:
            def invoke(self, messages):
                return {"raw": AIMessage(content=""), "parsed": schema(ok=True, word="pong"), "parsing_error": None}

        return Runnable()

    def bind_tools(self, tools):
        parent = self

        class Runnable:
            def invoke(self, messages):
                calls = [{"name": "get_server_time", "args": {"timezone": "Asia/Kolkata"}, "id": "1"}]
                return AIMessage(content="", tool_calls=calls if parent.tool_call else [])

        return Runnable()


def test_probes_every_declared_capability(flash):
    results = ModelProber(chat_factory=lambda model, timeout: ProbeChat()).probe(flash)

    assert [r.capability for r in results] == ["text", "structured_output", "tool_calling", "vision", "reasoning"]
    assert all(r.ok for r in results)


def test_probe_reports_a_capability_that_does_not_work(llama):
    results = {r.capability: r for r in ModelProber(chat_factory=lambda m, t: ProbeChat(tool_call=False)).probe(llama)}

    assert results["text"].ok
    assert not results["tool_calling"].ok
    assert "without calling the tool" in results["tool_calling"].detail
    assert "vision" not in results  # not declared, not probed


def test_setup_failure_is_reported_not_raised(flash):
    def factory(model, timeout):
        raise RuntimeError("Environment variable GEMINI_API_KEY is not set")

    results = ModelProber(chat_factory=factory).probe(flash)

    assert len(results) == 1
    assert (results[0].capability, results[0].ok) == ("setup", False)
    assert "GEMINI_API_KEY" in results[0].detail


def test_only_the_given_probes_run(flash):
    results = ModelProber(chat_factory=lambda m, t: ProbeChat(), probes=[VisionProbe()]).probe(flash)

    assert [r.capability for r in results] == ["vision"]
