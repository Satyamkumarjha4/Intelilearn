"""Unit under test: `lessons.origins.OriginVerifier`, which decides why a lesson was made from what the client claims.

Why: the origin of a lesson (made directly, or recommended by a test result) will decide what a later pricing feature
charges and which offers are shown, so the client's word is never enough. A recommendation must point at the caller's
own graded attempt and at a topic that attempt really told them to revisit; a follow-up or a quiz result can only come
from the server's own features, which do not exist yet in this phase.

Use cases:
- a direct lesson has the origin direct and no recommendation
- a direct lesson that names a recommendation is refused, because the two disagree
- a recommendation that names the caller's own graded attempt and one of its topics to revisit is accepted, with the
  topic as the attempt wrote it and the attempt id as text; the topic is matched ignoring case and spacing
- a recommendation without the attempt and topic, with an attempt id that is not an id, or with something that is not an
  object is refused, naming the field
- a recommendation for an attempt that does not exist, belongs to someone else, or is not graded is refused with one
  message that does not say which, so another learner's attempts cannot be probed
- a recommendation for a topic the attempt did not list is refused
- a follow-up and a quiz result are refused for now, and an origin that does not exist is refused
- a refusal is a 400 that names the field
"""

import uuid

import pytest
from rest_framework.exceptions import ValidationError

from lessons.models import TestSubmission
from lessons.origins import OriginVerifier

pytestmark = pytest.mark.django_db

CARD = {"complete": True, "score": {"awarded": 4, "available": 20, "percent": 20}, "questions": [],
        "topics_to_revisit": ["Loop invariants", "Off by one"]}  # fmt: skip


def graded(lesson, **fields):
    return TestSubmission.objects.create(lesson=lesson, status="graded", result=CARD, **fields)


def refused(user, origin, recommended_from=None):
    with pytest.raises(ValidationError) as caught:
        OriginVerifier().verify(user, origin, recommended_from)
    return caught.value.detail


class TestDirect:
    def test_a_direct_lesson_has_no_recommendation(self, user):
        verified = OriginVerifier().verify(user, "direct", None)

        assert (verified.origin, verified.recommended_from) == ("direct", None)

    def test_a_direct_lesson_that_names_a_recommendation_is_refused(self, user, lesson):
        detail = refused(user, "direct", {"attempt_id": str(graded(lesson).pk), "topic": "Off by one"})

        assert "recommended_from" in detail


class TestRecommendation:
    def test_the_callers_own_graded_attempt_and_one_of_its_topics_is_accepted(self, user, lesson):
        attempt = graded(lesson)

        verified = OriginVerifier().verify(user, "recommendation", {"attempt_id": attempt.pk, "topic": "  off BY one "})

        assert verified.origin == "recommendation"
        assert verified.recommended_from == {"attempt_id": str(attempt.pk), "topic": "Off by one"}

    @pytest.mark.parametrize("given", [None, {}, {"topic": "Off by one"}, {"attempt_id": "x"}, "text", ["a"]])
    def test_a_recommendation_without_an_attempt_and_a_topic_is_refused(self, user, given):
        assert "recommended_from" in refused(user, "recommendation", given)

    def test_an_attempt_id_that_is_not_an_id_is_refused(self, user):
        assert "recommended_from" in refused(user, "recommendation", {"attempt_id": "nope", "topic": "Off by one"})

    def test_an_attempt_that_does_not_exist_is_refused(self, user):
        given = {"attempt_id": str(uuid.uuid4()), "topic": "Off by one"}

        assert "recommended_from" in refused(user, "recommendation", given)

    def test_another_learners_attempt_is_refused_with_the_same_message_as_a_missing_one(
        self, user, other_user, make_lesson
    ):
        theirs = graded(make_lesson(owner=other_user))
        missing = refused(user, "recommendation", {"attempt_id": str(uuid.uuid4()), "topic": "Off by one"})

        other = refused(user, "recommendation", {"attempt_id": str(theirs.pk), "topic": "Off by one"})

        assert str(other) == str(missing)

    @pytest.mark.parametrize("status", ["generating", "in_progress", "grading", "failed"])
    def test_an_attempt_that_is_not_graded_is_refused(self, user, lesson, status):
        attempt = TestSubmission.objects.create(lesson=lesson, status=status, result=CARD)

        assert "recommended_from" in refused(
            user, "recommendation", {"attempt_id": str(attempt.pk), "topic": "Off by one"}
        )

    def test_a_topic_the_attempt_did_not_list_is_refused(self, user, lesson):
        attempt = graded(lesson)

        assert "recommended_from" in refused(
            user, "recommendation", {"attempt_id": str(attempt.pk), "topic": "Recursion"}
        )


class TestOthers:
    @pytest.mark.parametrize("origin", ["followup", "quiz_result"])
    def test_an_origin_only_the_server_can_set_is_refused_for_now(self, user, origin):
        assert "origin" in refused(user, origin)

    def test_an_origin_that_does_not_exist_is_refused(self, user):
        assert "origin" in refused(user, "friend")

    def test_a_refusal_is_a_400_that_names_the_field(self, user):
        with pytest.raises(ValidationError) as caught:
            OriginVerifier().verify(user, "followup", None)

        assert caught.value.status_code == 400 and list(caught.value.detail) == ["origin"]
