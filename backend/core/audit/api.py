"""The two persona steps that cannot be done honestly in the database: buying a plan and having a history.

Both go through the app's own endpoints, in this process, signed in as the persona (`force_authenticate`), so the
rows come from the real code: an order paid by the fake gateway's own signed callback, and a lesson that the worker
builds from the fake LLM. Nothing is written by hand that a learner's screens could not have produced.
"""

import json
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from rest_framework.test import APIClient

from payments.fake import FakeGateway

from .errors import SeedFailed


class Calls:
    """A signed-in in-process client that turns an unexpected status into `SeedFailed`."""

    def __init__(self, user):
        self.client = APIClient(SERVER_NAME="localhost")
        self.client.force_authenticate(user)

    def call(self, method: str, path: str, body: dict | None = None, expect: tuple[int, ...] = (200, 201, 202)) -> dict:
        reply = getattr(self.client, method)(path, body or {}, format="json")
        if reply.status_code not in expect:
            raise SeedFailed(f"{method.upper()} {path} answered {reply.status_code}: {str(reply.content[:200])}")
        return reply.json() if reply.content else {}


class ApiPlanPurchaser:
    """Buys a plan through `POST /api/payments/orders` and pays it with the fake gateway's own signed callback."""

    def __init__(self, secret: Callable[[], str] = FakeGateway.secret):
        self.secret = secret

    def buy(self, user, plan_key: str, quantity: int = 1) -> None:
        order = Calls(user).call(
            "post", "/api/payments/orders", {"plan": plan_key, "quantity": quantity, "gateway": "fake"}
        )
        body = json.dumps(
            {
                "id": f"audit-{uuid.uuid4().hex}",
                "type": "succeeded",
                "provider_ref": f"fake_{order['id']}",
                "payment_ref": f"pay_{order['id'][:8]}",
                "amount_paise": order["amount_paise"],
                "currency": "INR",
                "occurred_at": datetime.now(UTC).isoformat(),
            }
        ).encode()
        reply = APIClient(SERVER_NAME="localhost").post(
            "/api/payments/webhooks/fake",
            data=body,
            content_type="application/json",
            HTTP_X_FAKE_SIGNATURE=FakeGateway.sign(self.secret(), body),
        )
        if reply.status_code != 200:
            raise SeedFailed(f"the fake gateway's callback answered {reply.status_code}")


class ApiLearnerHistory:
    """A lesson built by the worker, two test attempts (the second is the retest), a cheat sheet and a quick quiz.

    It waits for the worker, so the stack must be up; a build that does not finish in `timeout_s` fails with a
    message that names the lesson and what it last saw.
    """

    TOPIC = "Binary search"

    def __init__(
        self,
        *,
        timeout_s: float = 300,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        calls: Callable[[object], "Calls"] = Calls,
    ):
        self.timeout_s, self.sleep, self.clock, self.calls = timeout_s, sleep, clock, calls

    def build(self, user) -> None:
        calls = self.calls(user)
        lesson_id = calls.call("post", "/api/lessons", {"topic": self.TOPIC, "entry": "self_rating", "self_rating": 4})[
            "lesson_id"
        ]
        self._until(lambda: calls.call("get", f"/api/lessons/{lesson_id}"), self._ready, f"lesson {lesson_id}")
        for number in (1, 2):  # the first attempt, then the retest
            attempt_id = self._open_attempt(calls, lesson_id, number)
            calls.call("post", f"/api/lessons/{lesson_id}/test/attempts/{attempt_id}/submit", {})
        calls.call("post", f"/api/lessons/{lesson_id}/materials", {"kinds": ["cheat_sheet"]})
        self._until(
            lambda: calls.call("get", f"/api/lessons/{lesson_id}"),
            lambda lesson: self._ready(lesson) and "cheat_sheet" in (lesson.get("materials") or []),
            f"the cheat sheet of lesson {lesson_id}",
        )
        quiz_id = calls.call(
            "post",
            "/api/quick-quizzes",
            {
                "source": {"type": "lessons", "lesson_ids": [lesson_id]},
                "num_questions": 5,
                "types": ["mcq"],
                "level": {"mode": "self_rating", "rating": 4},
            },
        )["quiz_id"]
        self._until(
            lambda: calls.call("get", f"/api/quick-quizzes/{quiz_id}"),
            lambda quiz: quiz.get("stage") == "ready",
            f"quick quiz {quiz_id}",
        )

    def _open_attempt(self, calls, lesson_id: str, number: int) -> str:
        """Starts an attempt and waits until it can be answered: a retake's questions are written by the worker."""
        attempt_id = calls.call("post", f"/api/lessons/{lesson_id}/test/attempts")["attempt_id"]
        self._until(
            lambda: calls.call("get", f"/api/lessons/{lesson_id}/test/attempts/{attempt_id}"),
            lambda attempt: attempt.get("status") == "in_progress",
            f"attempt {number} of lesson {lesson_id}",
        )
        return attempt_id

    @staticmethod
    def _ready(lesson: dict) -> bool:
        return lesson.get("stage") == "ready" and not lesson.get("active_run_id")

    def _until(self, read: Callable[[], dict], done: Callable[[dict], bool], what: str) -> dict:
        deadline = self.clock() + self.timeout_s
        seen: dict = {}
        while self.clock() < deadline:
            seen = read()
            if done(seen):
                return seen
            self.sleep(1)
        raise SeedFailed(
            f"{what} was not ready after {self.timeout_s:.0f}s (last stage: {seen.get('stage')!r}); "
            "is the worker running?"
        )
