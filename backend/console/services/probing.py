"""Testing one model from the console: the same capability probes as `manage.py probe_models`, within a time limit.

`ModelProber` runs the probes with one client timeout for all of them, so a slow model could take several timeouts in
a row. The console is a request somebody is waiting on, so `ModelProbeService` runs the model's probes one by one under
one deadline: each gets a client timeout of the time left, and once it is spent the rest are reported as timed out.
"""

import math
import time
from collections.abc import Callable
from dataclasses import dataclass

from llm_registry import providers
from llm_registry.probes import ModelProber, ProbeResult


@dataclass(frozen=True)
class ProbeOutcome:
    ok: bool
    latency_s: float | None  # of the plain text call, the basic round trip; None if it never ran
    error: str | None  # the first thing that went wrong, as "capability: detail"
    checks: list[ProbeResult]


class ModelProbeService:
    TIMEOUT_S = 20

    def __init__(self, chat_factory=None, clock: Callable[[], float] = time.monotonic, timeout_s: int = TIMEOUT_S):
        self._chat_factory, self._clock, self._timeout_s = chat_factory, clock, timeout_s

    def probe(self, llm_model) -> ProbeOutcome:
        # Looked up now, not when the service is built, so a test (or the shell) can swap
        # `providers.CHAT_MODEL_FACTORY`.
        factory = self._chat_factory or providers.CHAT_MODEL_FACTORY
        deadline = self._clock() + self._timeout_s
        checks: list[ProbeResult] = []
        for probe in ModelProber.DEFAULT_PROBES:
            if not probe.applies_to(llm_model):
                continue
            left = deadline - self._clock()
            if left <= 0:
                message = f"Timed out: the test did not finish within {self._timeout_s} s."
                checks.append(ProbeResult(probe.capability, False, 0, message))
                break
            results = ModelProber(chat_factory=factory, probes=(probe,), timeout_s=max(1, math.ceil(left))).probe(
                llm_model
            )
            checks.extend(results)
            if any(result.capability == "setup" for result in results):
                break  # the client could not even be built (no key, say): the other probes would fail the same way
        return self._outcome(checks)

    @staticmethod
    def _outcome(checks: list[ProbeResult]) -> ProbeOutcome:
        failed = next((check for check in checks if not check.ok), None)
        text = next((check for check in checks if check.capability == "text"), None)
        return ProbeOutcome(
            ok=failed is None and bool(checks),
            latency_s=None if text is None else round(text.latency_ms / 1000, 3),
            error=None if failed is None else f"{failed.capability}: {failed.detail}",
            checks=checks,
        )
