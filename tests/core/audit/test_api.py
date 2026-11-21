"""Unit under test: `core.audit.api`: the persona steps that go through the app's own endpoints (`Calls`,
`ApiPlanPurchaser`, `ApiLearnerHistory`).

Why: a plan and a history made by hand in the database would be rows no screen could have produced. Going through the
endpoints means the audit starts from what the real code makes. These tests prove the wiring: the plan really is
bought and paid by the fake gateway's signed callback (real endpoints, real fulfilment), and the history asks for the
right things in the right order, waits for the worker, and fails with a message that says what it was waiting for.

Use cases:
- Calls turns an unexpected status into SeedFailed that names the call and the status
- ApiPlanPurchaser buys a plan: the order is paid, the purchase is fulfilled and the credits arrive
- ApiLearnerHistory asks for the lesson, waits until it is ready, takes two test attempts (the second is the retest,
  whose questions the worker writes, so it waits until the attempt can be answered), asks for the cheat sheet and
  waits for it, asks for a quick quiz from the lesson and waits until it is ready
- a build that is not ready in time fails, naming what it waited for and asking whether the worker is running
"""

import pytest

from core.audit.api import ApiLearnerHistory, ApiPlanPurchaser, Calls
from core.audit.errors import SeedFailed
from credits.ledger import Ledger
from credits.models import PlanPurchase
from credits.plans.seed import PlanSeed

pytestmark = pytest.mark.django_db


class TestCalls:
    def test_an_unexpected_status_is_a_seed_failure_that_names_the_call(self, user):
        with pytest.raises(SeedFailed, match=r"GET /api/lessons/no-such-lesson answered 404"):
            Calls(user).call("get", "/api/lessons/no-such-lesson")


class TestPlanPurchaser:
    def test_the_plan_is_bought_paid_by_the_signed_callback_and_fulfilled(self, user, settings):
        settings.PAYMENT_ALLOW_FAKE_GATEWAY = True
        settings.PAYMENT_GATEWAYS_ENABLED = ["fake"]
        settings.PAYMENT_DEFAULT_GATEWAY = "fake"
        settings.PAYMENT_FAKE_GATEWAY_SECRET = "audit-test-secret"
        settings.PAYMENT_RETURN_BASE_URL = "http://localhost:7200"
        PlanSeed().apply()

        ApiPlanPurchaser().buy(user, "monthly_pro")

        purchase = PlanPurchase.objects.get(user=user)
        assert purchase.plan.key == "monthly_pro" and purchase.status == PlanPurchase.Status.FULFILLED
        assert Ledger().balance(user) >= 500

    def test_a_callback_the_gateway_refuses_is_a_seed_failure(self, user, settings):
        settings.PAYMENT_ALLOW_FAKE_GATEWAY = True
        settings.PAYMENT_GATEWAYS_ENABLED = ["fake"]
        settings.PAYMENT_DEFAULT_GATEWAY = "fake"
        settings.PAYMENT_FAKE_GATEWAY_SECRET = "audit-test-secret"
        settings.PAYMENT_RETURN_BASE_URL = "http://localhost:7200"
        PlanSeed().apply()

        with pytest.raises(SeedFailed, match="callback answered 400"):
            ApiPlanPurchaser(secret=lambda: "not-the-gateways-secret").buy(user, "monthly_pro")

        assert not PlanPurchase.objects.filter(user=user, status=PlanPurchase.Status.FULFILLED).exists()


class Script:
    """A scripted `Calls`: each GET of a lesson or quiz answers from a queue, and every call is remembered."""

    def __init__(self, lesson_states, quiz_states, attempt_states=()):
        self.log = []
        self.lessons, self.quizzes = list(lesson_states), list(quiz_states)
        self.attempts = list(attempt_states) or [{"status": "in_progress"}]

    def __call__(self, user):
        return self

    def call(self, method, path, body=None, expect=(200, 201, 202)):
        self.log.append((method, path))
        if method == "post" and path == "/api/lessons":
            return {"lesson_id": "L1"}
        if method == "post" and path.endswith("/test/attempts"):
            return {"attempt_id": f"A{sum(1 for m, p in self.log if p.endswith('/test/attempts'))}"}
        if method == "post" and path == "/api/quick-quizzes":
            return {"quiz_id": "Q1"}
        if method == "get" and "/test/attempts/" in path:
            return self.attempts.pop(0) if len(self.attempts) > 1 else self.attempts[0]
        if method == "get" and path == "/api/lessons/L1":
            return self.lessons.pop(0) if len(self.lessons) > 1 else self.lessons[0]
        if method == "get" and path == "/api/quick-quizzes/Q1":
            return self.quizzes.pop(0) if len(self.quizzes) > 1 else self.quizzes[0]
        return {}


READY = {"stage": "ready", "active_run_id": None, "materials": ["cheat_sheet"]}
BUILDING = {"stage": "building", "active_run_id": "R1", "materials": []}


class TestHistory:
    def test_it_asks_for_each_thing_in_order_and_waits_for_the_worker(self, user):
        script = Script(
            [BUILDING, READY],
            [{"stage": "building"}, {"stage": "ready"}],
            [{"status": "generating"}, {"status": "generating"}, {"status": "in_progress"}],
        )
        history = ApiLearnerHistory(sleep=lambda s: None, calls=script)

        history.build(user)

        posts = [path for method, path in script.log if method == "post"]
        assert posts == [
            "/api/lessons",
            "/api/lessons/L1/test/attempts",
            "/api/lessons/L1/test/attempts/A1/submit",
            "/api/lessons/L1/test/attempts",
            "/api/lessons/L1/test/attempts/A2/submit",
            "/api/lessons/L1/materials",
            "/api/quick-quizzes",
        ]
        assert ("get", "/api/quick-quizzes/Q1") in script.log
        # the retest is not answered until its questions are written: a submit comes after a read that said so
        reads = [
            i for i, (m, p) in enumerate(script.log) if m == "get" and p.startswith("/api/lessons/L1/test/attempts/")
        ]
        submits = [i for i, (m, p) in enumerate(script.log) if m == "post" and p.endswith("/submit")]
        assert reads[0] < submits[0] and reads[-1] < submits[-1]

    def test_a_build_that_is_not_ready_in_time_says_what_it_waited_for(self, user):
        ticks = iter(range(0, 10_000, 100))
        script = Script([BUILDING], [])
        history = ApiLearnerHistory(timeout_s=250, sleep=lambda s: None, clock=lambda: next(ticks), calls=script)

        with pytest.raises(SeedFailed, match=r"lesson L1 was not ready after 250s.*'building'.*worker"):
            history.build(user)
