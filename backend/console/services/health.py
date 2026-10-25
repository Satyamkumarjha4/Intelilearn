"""The overview's health card: the same checks as `GET /api/health`, plus how many Celery workers answered."""

import time
from collections.abc import Sequence
from dataclasses import asdict

from core.health import CeleryHealthCheck, CheckResult, DatabaseHealthCheck, HealthCheck, RedisHealthCheck


class ConsoleHealth:
    def __init__(self, checks: Sequence[HealthCheck] | None = None, celery: CeleryHealthCheck | None = None):
        self._checks = tuple(checks) if checks is not None else (DatabaseHealthCheck(), RedisHealthCheck())
        self._celery = celery if celery is not None else CeleryHealthCheck()

    def report(self) -> dict:
        components = {check.name: check.run() for check in self._checks}
        celery, workers = self._workers()
        components["celery"] = celery
        status = "ok" if all(result.ok for result in components.values()) else "degraded"
        return {"status": status, **{name: asdict(result) for name, result in components.items()}, "workers": workers}

    def _workers(self) -> tuple[CheckResult, int]:
        """One ping gives both the check's result and the count (`HealthCheck.run` would ping a second time)."""
        started = time.perf_counter()
        try:
            workers = self._celery.worker_count()
        except Exception as exc:  # an unreachable broker is a result to show, not an error page
            return CheckResult(False, self._ms(started), str(exc)), 0
        detail = f"{workers} worker(s)" if workers else "no workers responded"
        return CheckResult(bool(workers), self._ms(started), detail), workers

    @staticmethod
    def _ms(started: float) -> int:
        return round((time.perf_counter() - started) * 1000)
