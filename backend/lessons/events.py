"""Run progress: what nodes emit, what the browser receives, and the Redis pub/sub in between (Observer).

Nodes emit plain dicts through LangGraph's custom stream. The `FlowRunner` translates them into `RunEvent`s
(the vocabulary in docs/api.md) and publishes them on `run:{id}:events`; `RunEventStream` relays that channel to a
browser as Server-Sent Events, starting with a snapshot so a late or reconnecting client catches up.
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Protocol

import redis
import redis.asyncio
from asgiref.sync import sync_to_async
from django.conf import settings

from .models import GraphRun, Stage

logger = logging.getLogger(__name__)

TERMINAL_EVENTS = frozenset({"awaiting_input", "done", "error", "cancelled"})


@dataclass(frozen=True)
class RunEvent:
    name: str
    data: dict

    @property
    def terminal(self) -> bool:
        """The run segment is over: the browser should refetch the lesson (and stop listening)."""
        return self.name in TERMINAL_EVENTS

    def to_sse(self) -> str:
        return f"event: {self.name}\ndata: {json.dumps(self.data)}\n\n"

    def to_json(self) -> str:
        return json.dumps({"event": self.name, "data": self.data})

    @classmethod
    def from_json(cls, text: str | bytes) -> "RunEvent":
        payload = json.loads(text)
        return cls(payload["event"], payload["data"])


class RunEventTranslator:
    """Graph stream chunks (`updates` and `custom` modes) → run events."""

    def translate(self, mode: str, chunk: dict) -> list[RunEvent]:
        if mode == "updates":
            return [RunEvent("node", {"node": node, "status": "done"}) for node in chunk if node != "__interrupt__"]
        if mode != "custom":
            return []
        kind = chunk.get("type")
        if kind == "node":
            return [RunEvent("node", {"node": chunk["node"], "status": chunk["status"]})]
        if kind == "attempt":
            data = {
                "node": chunk["node"],
                "status": "retrying",
                "attempt": chunk.get("attempt"),
                "reason": chunk["reason"],
            }
            return [RunEvent("node", data)]
        if kind == "retrying":
            data = {"node": chunk["node"], "model": chunk["model"], "kind": "retry"}
            return [RunEvent("model", data | {"attempt": chunk["attempt"], "reason": chunk["reason"]})]
        if kind == "fallback_model":
            data = {"node": chunk["node"], "model": chunk["model"], "kind": "fallback"}
            return [RunEvent("model", data | {"fallback_index": chunk["fallback_index"], "reason": chunk["reason"]})]
        if kind == "warning":
            return [RunEvent("warning", {"message": chunk["message"]})]
        return []


class EventPublisher(Protocol):
    def publish(self, run_id, event: RunEvent) -> None: ...


def channel(run_id) -> str:
    return f"run:{run_id}:events"


class RedisEventPublisher:
    """Publishes on the run's channel. A broken Redis must not stop a lesson from being built, so it only logs."""

    def __init__(self, client=None):
        self._client = client

    @property
    def client(self):
        if self._client is None:
            self._client = redis.Redis.from_url(settings.REDIS_URL)
        return self._client

    def publish(self, run_id, event: RunEvent) -> None:
        try:
            self.client.publish(channel(run_id), event.to_json())
        except redis.RedisError:
            logger.warning("Could not publish %s for run %s", event.name, run_id, exc_info=True)


class RunEventStream:
    """The body of `GET /runs/{id}/events`: snapshot, then the run's events, until a terminal one.

    It subscribes *before* reading the snapshot, so nothing published in between is lost. A snapshot of a run that
    already ended is followed by its terminal event, so a client that connects late still finishes.
    """

    def __init__(self, redis_url: str | None = None, heartbeat_s: float = 15):
        self.redis_url = redis_url
        self.heartbeat_s = heartbeat_s

    async def events(self, run_id, snapshot: Callable[[], dict]) -> AsyncIterator[str]:
        client = redis.asyncio.Redis.from_url(self.redis_url or settings.REDIS_URL)
        pubsub = client.pubsub(ignore_subscribe_messages=True)
        try:
            await pubsub.subscribe(channel(run_id))
            current = await sync_to_async(snapshot)()
            yield RunEvent("snapshot", current).to_sse()
            if (final := self.terminal_event(current)) is not None:
                yield final.to_sse()
                return
            loop = asyncio.get_running_loop()
            deadline = loop.time() + self.heartbeat_s
            while True:
                # get_message also returns None for housekeeping replies (the subscribe confirmation), so a None
                # only means "idle" once the heartbeat interval has really passed.
                message = await pubsub.get_message(timeout=max(deadline - loop.time(), 0))
                if message is None:
                    if loop.time() >= deadline:
                        yield ": ping\n\n"
                        deadline = loop.time() + self.heartbeat_s
                    continue
                event = RunEvent.from_json(message["data"])
                yield event.to_sse()
                if event.terminal:
                    return
                deadline = loop.time() + self.heartbeat_s
        finally:
            await pubsub.aclose()
            await client.aclose()

    @staticmethod
    def terminal_event(snapshot: dict) -> RunEvent | None:
        status = snapshot["status"]
        if status == "succeeded":
            return RunEvent("done", {"lesson_id": snapshot.get("lesson_id"), "stage": snapshot["stage"]})
        if status == "paused":
            return RunEvent("awaiting_input", {"kind": snapshot.get("awaiting")})
        if status == "failed":
            return RunEvent("error", {"message": snapshot.get("error") or "The run failed.", "code": "failed"})
        if status == "cancelled":
            return RunEvent("cancelled", {})
        return None


class RunSnapshot:
    """The state of a run as the stream's first event: enough for a client to catch up (see docs/api.md)."""

    AWAITING = {
        Stage.AWAITING_DIAGNOSTIC: "diagnostic",
        Stage.AWAITING_PREREQUISITE: "prerequisite",
        Stage.AWAITING_CHOICE: "mastery_choice",
    }

    def __init__(self, run_id):
        self.run_id = run_id

    def __call__(self) -> dict:
        run = GraphRun.objects.select_related("lesson").get(pk=self.run_id)
        return {
            "status": run.status,
            "stage": run.lesson.stage,
            "lesson_id": str(run.lesson_id),
            "node_status": run.node_status,
            "error": run.error,
            "awaiting": self.AWAITING.get(run.lesson.stage),
            "started_at": (run.started_at or run.created_at).isoformat(),
        }
