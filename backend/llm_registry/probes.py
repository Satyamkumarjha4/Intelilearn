"""'Test model' in the admin: one small real call per capability the model claims to have."""

import base64
import struct
import time
import zlib
from dataclasses import dataclass

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from .providers import build_chat_model
from .redaction import REDACTOR
from .resolver import ResolvedModel


def solid_png(rgb: tuple[int, int, int], size: int = 16) -> bytes:
    """A valid PNG of one colour, built in code so the probe needs no image file."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    row = b"\x00" + bytes(rgb) * size  # filter byte + pixels
    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)  # 8-bit RGB
    return (
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(row * size)) + chunk(b"IEND", b"")
    )


_RED_PNG = base64.b64encode(solid_png((220, 20, 20))).decode()


class _Ping(BaseModel):
    ok: bool = Field(description="Always true")
    word: str = Field(description="The word 'pong'")


@tool
def get_server_time(timezone: str) -> str:
    """Return the current time in the given IANA timezone."""
    return "12:00"


@dataclass
class ProbeResult:
    capability: str
    ok: bool
    latency_ms: int
    detail: str

    def __post_init__(self):
        self.detail = REDACTOR.redact(self.detail)  # shown in admin messages


def _run(capability: str, fn) -> ProbeResult:
    started = time.perf_counter()
    try:
        detail = fn()
        return ProbeResult(capability, True, int((time.perf_counter() - started) * 1000), detail)
    except Exception as exc:
        return ProbeResult(
            capability, False, int((time.perf_counter() - started) * 1000), f"{type(exc).__name__}: {exc}"
        )


def probe_model(llm_model, *, chat_factory=build_chat_model, timeout_s: int = 60) -> list[ProbeResult]:
    """Probe every capability the LLMModel row declares. Makes real API calls."""
    provider = llm_model.provider

    def resolved(effort: str = "none") -> ResolvedModel:
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

    try:
        chat = chat_factory(resolved(), timeout_s)
    except Exception as exc:  # e.g. missing API key: report it instead of crashing the admin action
        return [ProbeResult("setup", False, 0, f"{type(exc).__name__}: {exc}")]

    def text():
        reply = chat.invoke([HumanMessage("Reply with exactly the word: pong")])
        return f"replied {reply.text[:40]!r}"

    def structured():
        runnable = chat.with_structured_output(_Ping, method=llm_model.structured_output_method, include_raw=True)
        result = runnable.invoke([HumanMessage("Return ok=true and word='pong'.")])
        if result["parsed"] is None:
            raise ValueError(f"no parsed output ({result['parsing_error']})")
        return f"parsed {result['parsed']!r}"

    def tools():
        reply = chat.bind_tools([get_server_time]).invoke(
            [HumanMessage("What time is it in Asia/Kolkata? Use the tool.")]
        )
        if not reply.tool_calls:
            raise ValueError("the model answered without calling the tool")
        return f"called {reply.tool_calls[0]['name']}({reply.tool_calls[0]['args']})"

    def vision():
        image = {"type": "image", "base64": _RED_PNG, "mime_type": "image/png"}
        reply = chat.invoke(
            [HumanMessage(content=[{"type": "text", "text": "What colour is this image? One word."}, image])]
        )
        return f"replied {reply.text[:40]!r}"

    def reasoning():
        reply = chat_factory(resolved("low"), timeout_s).invoke(
            [HumanMessage("What is 17 * 23? Reply with the number.")]
        )
        return f"replied {reply.text[:40]!r}"

    results = [_run("text", text)]
    if llm_model.supports_structured_output:
        results.append(_run("structured_output", structured))
    if llm_model.supports_tool_calling:
        results.append(_run("tool_calling", tools))
    if llm_model.supports_vision:
        results.append(_run("vision", vision))
    if llm_model.supports_reasoning:
        results.append(_run("reasoning", reasoning))
    return results
