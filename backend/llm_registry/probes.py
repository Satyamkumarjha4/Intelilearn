"""'Test model' in the admin and `manage.py probe_models`: one small real call per capability a model claims.

ModelProber runs every CapabilityProbe that applies to the model (Strategy, one class per capability); each probe
times its call and turns any exception into a failed ProbeResult.
"""

import base64
import struct
import time
import zlib
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import ClassVar

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from .providers import CHAT_MODEL_FACTORY, ChatModelFactory
from .redaction import REDACTOR
from .resolver import ResolvedModel


@dataclass
class ProbeResult:
    capability: str
    ok: bool
    latency_ms: int
    detail: str

    def __post_init__(self):
        self.detail = REDACTOR.redact(self.detail)  # shown in admin messages


@dataclass(frozen=True)
class ProbeTarget:
    """The model under test: its row, a client at reasoning effort none, and a way to get one at another effort."""

    llm_model: object
    chat: object
    chat_at: Callable[[str], object]


class CapabilityProbe(ABC):
    capability: ClassVar[str]

    def applies_to(self, llm_model) -> bool:
        return True

    def run(self, target: ProbeTarget) -> ProbeResult:
        started = time.perf_counter()
        try:
            detail = self.check(target)
            return ProbeResult(self.capability, True, self._ms(started), detail)
        except Exception as exc:
            return ProbeResult(self.capability, False, self._ms(started), f"{type(exc).__name__}: {exc}")

    @abstractmethod
    def check(self, target: ProbeTarget) -> str:
        """Make the call; return what happened, or raise if the capability doesn't work."""

    @staticmethod
    def _ms(started: float) -> int:
        return int((time.perf_counter() - started) * 1000)


class TextProbe(CapabilityProbe):
    capability = "text"

    def check(self, target: ProbeTarget) -> str:
        reply = target.chat.invoke([HumanMessage("Reply with exactly the word: pong")])
        return f"replied {reply.text[:40]!r}"


class _Ping(BaseModel):
    ok: bool = Field(description="Always true")
    word: str = Field(description="The word 'pong'")


class StructuredOutputProbe(CapabilityProbe):
    capability = "structured_output"

    def applies_to(self, llm_model) -> bool:
        return llm_model.supports_structured_output

    def check(self, target: ProbeTarget) -> str:
        method = target.llm_model.structured_output_method
        runnable = target.chat.with_structured_output(_Ping, method=method, include_raw=True)
        result = runnable.invoke([HumanMessage("Return ok=true and word='pong'.")])
        if result["parsed"] is None:
            raise ValueError(f"no parsed output ({result['parsing_error']})")
        return f"parsed {result['parsed']!r}"


class ToolCallingProbe(CapabilityProbe):
    capability = "tool_calling"

    @staticmethod
    @tool
    def get_server_time(timezone: str) -> str:
        """Return the current time in the given IANA timezone."""
        return "12:00"

    def applies_to(self, llm_model) -> bool:
        return llm_model.supports_tool_calling

    def check(self, target: ProbeTarget) -> str:
        reply = target.chat.bind_tools([self.get_server_time]).invoke(
            [HumanMessage("What time is it in Asia/Kolkata? Use the tool.")]
        )
        if not reply.tool_calls:
            raise ValueError("the model answered without calling the tool")
        return f"called {reply.tool_calls[0]['name']}({reply.tool_calls[0]['args']})"


class VisionProbe(CapabilityProbe):
    capability = "vision"

    @staticmethod
    def solid_png(rgb: tuple[int, int, int], size: int = 16) -> bytes:
        """A valid PNG of one colour, built in code so the probe needs no image file."""

        def chunk(kind: bytes, data: bytes) -> bytes:
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

        row = b"\x00" + bytes(rgb) * size  # filter byte + pixels
        header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)  # 8-bit RGB
        idat = zlib.compress(row * size)
        return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")

    def applies_to(self, llm_model) -> bool:
        return llm_model.supports_vision

    def check(self, target: ProbeTarget) -> str:
        image = {"type": "image", "base64": base64.b64encode(self.solid_png((220, 20, 20))).decode(),
                 "mime_type": "image/png"}  # fmt: skip
        reply = target.chat.invoke(
            [HumanMessage(content=[{"type": "text", "text": "What colour is this image? One word."}, image])]
        )
        return f"replied {reply.text[:40]!r}"


class ReasoningProbe(CapabilityProbe):
    capability = "reasoning"

    def applies_to(self, llm_model) -> bool:
        return llm_model.supports_reasoning

    def check(self, target: ProbeTarget) -> str:
        reply = target.chat_at("low").invoke([HumanMessage("What is 17 * 23? Reply with the number.")])
        return f"replied {reply.text[:40]!r}"


class ModelProber:
    DEFAULT_PROBES: ClassVar[tuple[CapabilityProbe, ...]] = (
        TextProbe(),
        StructuredOutputProbe(),
        ToolCallingProbe(),
        VisionProbe(),
        ReasoningProbe(),
    )

    def __init__(
        self,
        *,
        chat_factory: ChatModelFactory = CHAT_MODEL_FACTORY,
        probes: Sequence[CapabilityProbe] | None = None,
        timeout_s: int = 60,
    ):
        self._chat_factory = chat_factory
        self._probes = tuple(probes) if probes is not None else self.DEFAULT_PROBES
        self._timeout_s = timeout_s

    def probe(self, llm_model) -> list[ProbeResult]:
        """Probe every capability the LLMModel row declares. Makes real API calls."""
        try:
            chat = self._chat(llm_model, "none")
        except Exception as exc:  # e.g. missing API key: report it instead of crashing the admin action
            return [ProbeResult("setup", False, 0, f"{type(exc).__name__}: {exc}")]
        target = ProbeTarget(llm_model, chat, lambda effort: self._chat(llm_model, effort))
        return [probe.run(target) for probe in self._probes if probe.applies_to(llm_model)]

    def _chat(self, llm_model, effort: str):
        return self._chat_factory(self._resolved(llm_model, effort), self._timeout_s)

    @staticmethod
    def _resolved(llm_model, effort: str) -> ResolvedModel:
        provider = llm_model.provider
        params, reasoning = provider.profile.apply_reasoning(
            llm_model.reasoning_control,
            effort,
            dict(llm_model.default_params),
            disables_sampling=llm_model.reasoning_disables_sampling,
        )
        return ResolvedModel(
            provider_key=provider.key,
            provider_kind=provider.kind,
            model_name=llm_model.name,
            params=params,
            reasoning=reasoning,
            reasoning_effort=effort,
            structured_output_method=llm_model.structured_output_method,
            api_key_env=provider.api_key_env,
            base_url=provider.base_url,
            max_retries=0,
        )
