"""Unit under test: `lessons.idempotency`, the optional `Idempotency-Key` header on the creation endpoints
(`IdempotencyKey`, `CacheIdempotencyStore`, `IdempotentRequest`).

Why: a double click or a client retry on "start a lesson" would make two lessons today, and once actions are metered,
two authorizations. A replayed key must return the first answer and do nothing else; a key must never leak between
learners or between different requests.

Use cases:
- no header means no idempotency, and the request is performed
- a valid header is accepted; an empty, overlong or non-printable one is refused with 400
- the same header on a different learner, endpoint or body is a different request
- the first success is remembered and replayed with the same status and body, without performing the request again
- a failed request is not remembered, so it can be tried again with the same key
- a second request with the same key while the first is still being performed is refused with 409
- remembered answers expire after `IDEMPOTENCY_TTL_S`
"""

import pytest
from django.test import override_settings
from rest_framework.response import Response

from lessons.idempotency import (
    CacheIdempotencyStore,
    IdempotencyKey,
    IdempotentRequest,
    InvalidIdempotencyKey,
    RequestInProgress,
    StoredResponse,
)


class Request:
    def __init__(self, user_id=1, key=None):
        self.user = type("U", (), {"pk": user_id})()
        self.headers = {"Idempotency-Key": key} if key is not None else {}


class TestIdempotencyKey:
    def test_no_header_means_no_key(self):
        assert IdempotencyKey.of(Request(), "lessons.create", {"topic": "a"}) is None

    def test_a_valid_header_is_accepted(self):
        assert IdempotencyKey.of(Request(key="abc-123_X"), "lessons.create", {}).header == "abc-123_X"

    @pytest.mark.parametrize("header", ["", "   ", "x" * 129, "has space", "tab\tin", "café", "a\nb"])
    def test_an_empty_overlong_or_non_printable_header_is_refused(self, header):
        with pytest.raises(InvalidIdempotencyKey) as raised:
            IdempotencyKey.of(Request(key=header), "lessons.create", {})
        assert raised.value.status_code == 400 and raised.value.get_codes() == "invalid_idempotency_key"

    def test_the_same_header_is_a_different_request_for_another_learner_endpoint_or_body(self):
        base = IdempotencyKey.of(Request(1, "k"), "lessons.create", {"topic": "a"})

        assert base.cache_key == IdempotencyKey.of(Request(1, "k"), "lessons.create", {"topic": "a"}).cache_key
        assert base.cache_key != IdempotencyKey.of(Request(2, "k"), "lessons.create", {"topic": "a"}).cache_key
        assert base.cache_key != IdempotencyKey.of(Request(1, "k"), "materials.request", {"topic": "a"}).cache_key
        assert base.cache_key != IdempotencyKey.of(Request(1, "k"), "lessons.create", {"topic": "b"}).cache_key

    def test_the_order_of_the_body_s_fields_does_not_matter(self):
        one = IdempotencyKey.of(Request(1, "k"), "s", {"a": 1, "b": 2})
        two = IdempotencyKey.of(Request(1, "k"), "s", {"b": 2, "a": 1})

        assert one.cache_key == two.cache_key


class TestIdempotentRequest:
    def perform_counting(self, counter):
        def perform(client_key):
            counter.append(client_key)
            return Response({"lesson_id": "l1"}, status=202)

        return perform

    def test_without_a_header_the_request_is_performed_every_time(self):
        calls = []
        gate = IdempotentRequest(CacheIdempotencyStore())

        for _ in range(2):
            gate.run(Request(), "lessons.create", {}, self.perform_counting(calls))

        assert calls == ["", ""]

    def test_the_first_success_is_replayed_without_performing_the_request_again(self):
        calls = []
        gate = IdempotentRequest(CacheIdempotencyStore())
        request = Request(key="k1")

        first = gate.run(request, "lessons.create", {"t": 1}, self.perform_counting(calls))
        second = gate.run(request, "lessons.create", {"t": 1}, self.perform_counting(calls))

        assert calls == ["k1"]
        assert (second.status_code, second.data) == (first.status_code, first.data) == (202, {"lesson_id": "l1"})
        assert second["Idempotent-Replayed"] == "true" and "Idempotent-Replayed" not in first

    def test_a_failed_request_is_not_remembered_so_the_key_can_be_used_again(self):
        gate = IdempotentRequest(CacheIdempotencyStore())
        request = Request(key="k2")

        def boom(client_key):
            raise RuntimeError("no")

        with pytest.raises(RuntimeError):
            gate.run(request, "lessons.create", {}, boom)
        calls = []
        gate.run(request, "lessons.create", {}, self.perform_counting(calls))

        assert calls == ["k2"]

    def test_a_response_that_is_not_a_success_is_not_remembered(self):
        gate = IdempotentRequest(CacheIdempotencyStore())
        request = Request(key="k3")

        gate.run(request, "lessons.create", {}, lambda client_key: Response({"detail": "x"}, status=409))
        calls = []
        gate.run(request, "lessons.create", {}, self.perform_counting(calls))

        assert calls == ["k3"]

    def test_a_second_request_while_the_first_is_being_performed_is_refused(self):
        store = CacheIdempotencyStore()
        gate = IdempotentRequest(store)
        request = Request(key="k4")

        def inner(client_key):
            with pytest.raises(RequestInProgress) as raised:
                gate.run(request, "lessons.create", {}, lambda c: Response({}, status=202))
            assert raised.value.status_code == 409 and raised.value.get_codes() == "request_in_progress"
            return Response({"ok": True}, status=202)

        assert gate.run(request, "lessons.create", {}, inner).status_code == 202


class TestCacheIdempotencyStore:
    def test_remembers_and_replays_what_it_was_given(self):
        store = CacheIdempotencyStore()

        assert store.replay("a") is None
        store.remember("a", StoredResponse(202, {"x": 1}))

        assert store.replay("a") == StoredResponse(202, {"x": 1})

    def test_only_one_claim_wins_until_it_is_released(self):
        store = CacheIdempotencyStore()

        assert store.claim("b") is True
        assert store.claim("b") is False
        store.release("b")
        assert store.claim("b") is True

    @override_settings(IDEMPOTENCY_TTL_S=1)
    def test_remembered_answers_expire_after_the_configured_time(self):
        import time

        store = CacheIdempotencyStore()
        store.remember("c", StoredResponse(202, {}))
        assert store.replay("c") is not None

        time.sleep(1.2)

        assert store.replay("c") is None
