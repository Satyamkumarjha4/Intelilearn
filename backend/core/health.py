"""Health checks for the services the API depends on (Strategy per dependency, aggregated by HealthService)."""

import time
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import asdict, dataclass

import redis
from django.conf import settings
from django.db import connection

from config.celery import app as celery_app


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    latency_ms: int
    detail: str


@dataclass(frozen=True)
class HealthReport:
    components: dict[str, CheckResult]

    @property
    def ok(self) -> bool:
        return all(result.ok for result in self.components.values())

    @property
    def status(self) -> str:
        return "ok" if self.ok else "degraded"

    def to_dict(self) -> dict:
        return {"status": self.status, **{name: asdict(result) for name, result in self.components.items()}}


class HealthCheck(ABC):
    name: str

    def run(self) -> CheckResult:
        started = time.perf_counter()
        try:
            detail = self.probe()
            return CheckResult(True, self._ms(started), detail)
        except Exception as exc:  # health checks report failures instead of raising
            return CheckResult(False, self._ms(started), str(exc))

    @abstractmethod
    def probe(self) -> str:
        """Reach the dependency; return a short description, or raise if it's unavailable."""

    @staticmethod
    def _ms(started: float) -> int:
        return round((time.perf_counter() - started) * 1000)


class DatabaseHealthCheck(HealthCheck):
    name = "database"

    def probe(self) -> str:
        with connection.cursor() as cursor:
            cursor.execute("select version()")
            return cursor.fetchone()[0].split(",")[0]


class RedisHealthCheck(HealthCheck):
    name = "redis"

    def __init__(self, url: str | None = None, timeout_s: float = 2):
        self._url, self._timeout_s = url, timeout_s

    def probe(self) -> str:
        client = redis.Redis.from_url(self._url or settings.REDIS_URL, socket_connect_timeout=self._timeout_s)
        return f"redis {client.info('server')['redis_version']}"


class CeleryHealthCheck(HealthCheck):
    name = "celery"

    def __init__(self, app=celery_app, timeout_s: float = 1.0):
        self._app, self._timeout_s = app, timeout_s

    def probe(self) -> str:
        replies = self._app.control.ping(timeout=self._timeout_s)
        if not replies:
            raise RuntimeError("no workers responded")
        return f"{len(replies)} worker(s)"


class HealthService:
    def __init__(self, checks: Sequence[HealthCheck] | None = None):
        self._checks = (
            tuple(checks) if checks is not None else (DatabaseHealthCheck(), RedisHealthCheck(), CeleryHealthCheck())
        )

    def report(self) -> HealthReport:
        return HealthReport({check.name: check.run() for check in self._checks})
