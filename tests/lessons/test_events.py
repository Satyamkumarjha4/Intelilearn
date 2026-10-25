"""Unit under test: `lessons.events`: `RunEvent` (what the browser receives), `RunEventTranslator` (graph stream chunks
→ run events), `RedisEventPublisher` (pub/sub per run) and `RunEventStream` (the Server-Sent Events body).

Why: this is how the learner watches a lesson being built, and how the browser learns that it is their turn to answer a
quiz. A translator that drops a terminal event leaves the page spinning forever; a stream that misses the events
published between connecting and the first snapshot shows a stale pipeline; a stream that never pings is cut by proxies.

Use cases:
- an event serialises as a Server-Sent Event, and only awaiting_input, done, error and cancelled are terminal
- node progress, attempts, model retries and fallbacks, and warnings are translated from the graph's stream
- unknown custom events and the interrupt marker are ignored
- the publisher puts events on the run's channel and a subscriber receives them
- the stream sends a snapshot first, relays published events, and stops after a terminal one
- the stream ends right after the snapshot when the run has already finished (it connected late)
- the stream pings while idle
- the first snapshot says where the run stands, including when it started (so the page can say "Started 2 min ago"),
  falling back to when it was queued
"""

import asyncio
import json

import pytest
import redis
from django.conf import settings
from django.utils import timezone

from lessons.events import RedisEventPublisher, RunEvent, RunEventStream, RunEventTranslator, RunSnapshot
from lessons.models import GraphRun, Lesson

translate = RunEventTranslator().translate


class TestRunEvent:
    def test_serialises_as_a_server_sent_event(self):
        event = RunEvent("node", {"node": "plan_lesson", "status": "done"})

        assert event.to_sse() == 'event: node\ndata: {"node": "plan_lesson", "status": "done"}\n\n'

    @pytest.mark.parametrize(
        ("name", "terminal"),
        [("awaiting_input", True), ("done", True), ("error", True), ("cancelled", True),
         ("snapshot", False), ("node", False), ("model", False), ("warning", False)],
    )  # fmt: skip
    def test_only_the_events_that_end_a_run_segment_are_terminal(self, name, terminal):
        assert RunEvent(name, {}).terminal is terminal

    def test_round_trips_through_json(self):
        event = RunEvent("warning", {"message": "Dropped a widget"})

        assert RunEvent.from_json(event.to_json()) == event


class TestTranslator:
    def test_a_node_starting_is_a_running_node_event(self):
        events = translate("custom", {"type": "node", "node": "plan_lesson", "status": "running"})

        assert events == [RunEvent("node", {"node": "plan_lesson", "status": "running"})]

    def test_a_node_finishing_is_a_done_node_event(self):
        events = translate("updates", {"validate_diagnostic": {"feedback": {}}})

        assert events == [RunEvent("node", {"node": "validate_diagnostic", "status": "done"})]

    def test_several_nodes_finishing_in_one_step_give_one_event_each(self):
        events = translate("updates", {"write_page": {}, "write_test": {}})

        assert [e.data["node"] for e in events] == ["write_page", "write_test"]

    def test_a_validation_retry_is_a_retrying_node_event_with_the_reason(self):
        chunk = {"type": "attempt", "node": "generate_diagnostic", "attempt": 2, "reason": "Needs 10 questions"}

        assert translate("custom", chunk) == [
            RunEvent(
                "node",
                {"node": "generate_diagnostic", "status": "retrying", "attempt": 2, "reason": "Needs 10 questions"},
            )
        ]

    def test_a_model_retry_is_a_model_event(self):
        chunk = {
            "type": "retrying",
            "node": "page.generate",
            "model": "gemini-flash",
            "attempt": 2,
            "reason": "Timeout",
        }

        assert translate("custom", chunk) == [
            RunEvent(
                "model",
                {"node": "page.generate", "model": "gemini-flash", "kind": "retry", "attempt": 2, "reason": "Timeout"},
            )
        ]

    def test_a_fallback_model_is_a_model_event(self):
        chunk = {
            "type": "fallback_model",
            "node": "page.generate",
            "model": "llama",
            "fallback_index": 1,
            "reason": "429",
        }

        assert translate("custom", chunk) == [
            RunEvent(
                "model",
                {"node": "page.generate", "model": "llama", "kind": "fallback", "fallback_index": 1, "reason": "429"},
            )
        ]

    def test_a_warning_passes_through(self):
        assert translate("custom", {"type": "warning", "message": "Dropped a widget"}) == [
            RunEvent("warning", {"message": "Dropped a widget"})
        ]

    def test_ignores_unknown_custom_events_and_the_interrupt_marker(self):
        assert translate("custom", {"type": "something_new"}) == []
        assert translate("updates", {"__interrupt__": ("pause",)}) == []


@pytest.fixture
def redis_client():
    client = redis.Redis.from_url(settings.REDIS_URL)
    yield client
    client.close()


class TestPublisher:
    def test_publishes_json_on_the_runs_channel(self, redis_client):
        pubsub = redis_client.pubsub(ignore_subscribe_messages=True)
        pubsub.subscribe("run:abc:events")
        pubsub.get_message(timeout=1)  # the subscribe confirmation

        RedisEventPublisher().publish("abc", RunEvent("done", {"stage": "ready"}))

        message = pubsub.get_message(timeout=2)
        assert json.loads(message["data"]) == {"event": "done", "data": {"stage": "ready"}}
        pubsub.close()

    def test_a_publisher_failure_never_breaks_the_run(self):
        class Broken:
            def publish(self, *args):
                raise redis.ConnectionError("down")

        RedisEventPublisher(client=Broken()).publish("abc", RunEvent("node", {}))  # must not raise


def snapshot_of(status="running", **extra):
    return lambda: {"status": status, "stage": "preparing_diagnostic", "node_status": {}, **extra}


async def collect(stream_events, publish=None, limit=20):
    """Read SSE chunks; `publish` is called once the stream has subscribed (after its snapshot)."""
    chunks = []
    async for chunk in stream_events:
        chunks.append(chunk)
        if len(chunks) == 1 and publish:
            publish()
        if len(chunks) >= limit:
            break
    return chunks


@pytest.mark.anyio
class TestStream:
    @pytest.fixture
    def anyio_backend(self):
        return "asyncio"

    async def test_sends_a_snapshot_then_relays_events_until_a_terminal_one(self, redis_client):
        stream = RunEventStream(heartbeat_s=5)
        publisher = RedisEventPublisher()

        def publish():
            publisher.publish("r1", RunEvent("node", {"node": "load_context", "status": "running"}))
            publisher.publish("r1", RunEvent("awaiting_input", {"kind": "diagnostic"}))
            publisher.publish("r1", RunEvent("node", {"node": "never_seen", "status": "running"}))

        chunks = await collect(stream.events("r1", snapshot_of()), publish)

        assert chunks[0].startswith("event: snapshot\n")
        assert 'event: node\ndata: {"node": "load_context", "status": "running"}' in chunks[1]
        assert chunks[2].startswith("event: awaiting_input\n")
        assert len(chunks) == 3

    async def test_ends_right_after_the_snapshot_when_the_run_already_finished(self):
        chunks = await collect(RunEventStream(heartbeat_s=5).events("r2", snapshot_of("succeeded", lesson_id="l1")))

        assert [c.split("\n")[0] for c in chunks] == ["event: snapshot", "event: done"]
        assert '"lesson_id": "l1"' in chunks[1]

    @pytest.mark.parametrize(
        ("status", "extra", "event"),
        [
            ("paused", {"awaiting": "diagnostic"}, "awaiting_input"),
            ("failed", {"error": "The model refused."}, "error"),
            ("cancelled", {}, "cancelled"),
        ],
    )
    async def test_a_late_connection_gets_the_terminal_event_matching_the_run(self, status, extra, event):
        chunks = await collect(RunEventStream(heartbeat_s=5).events("r3", snapshot_of(status, **extra)))

        assert chunks[-1].startswith(f"event: {event}\n")

    async def test_pings_while_idle(self):
        stream = RunEventStream(heartbeat_s=0.05)

        chunks = await asyncio.wait_for(collect(stream.events("r4", snapshot_of()), limit=3), timeout=3)

        assert chunks[1:] == [": ping\n\n", ": ping\n\n"]


@pytest.mark.django_db
class TestRunSnapshot:
    def run_of(self, user, **fields):
        lesson = Lesson.objects.create(owner=user, topic="Binary search", stage="generating_lesson")
        return GraphRun.objects.create(lesson=lesson, trigger="start", **fields)

    def test_says_where_the_run_stands_and_when_it_started(self, user):
        started = timezone.now()
        run = self.run_of(user, status="running", started_at=started, node_status={"plan_lesson": "done"})

        snapshot = RunSnapshot(run.id)()

        assert snapshot["status"] == "running" and snapshot["stage"] == "generating_lesson"
        assert snapshot["node_status"] == {"plan_lesson": "done"} and snapshot["awaiting"] is None
        assert snapshot["started_at"] == started.isoformat()

    def test_falls_back_to_when_the_run_was_queued(self, user):
        run = self.run_of(user)

        assert RunSnapshot(run.id)()["started_at"] == run.created_at.isoformat()
