"""Unit under test: the attempt side of `lessons.models`: `TestSubmission` as an attempt (its states, `seal`), the
`Question` record, and the new `FlowSettings` fields with their `clean`.

Why: an attempt is a learner's result and must not be changeable once it is over; the record of questions feeds the
exclusion list of every retake; and the settings decide how much a retake costs and where the bands lie, so a value that
makes no sense must be refused where it is edited.

Use cases:
- an attempt is open while it is generating or in progress, and not once it is graded or has failed
- the newest attempt comes first
- sealing an attempt closes it: answers, result, band, offer and the measured time are stored, and the marks only for a
  graded one
- sealing twice, or sealing an attempt that is not in progress, changes nothing and says the attempt is over
- a question on the record keeps its payload and is deleted with its lesson
- the new settings have their defaults, a Fail line at or above the Excellent line is refused, and a batch outside 5 to
  10 is refused
"""

from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from lessons.errors import AttemptSealed
from lessons.models import FlowSettings, Question, TestSubmission

pytestmark = pytest.mark.django_db

CARD = {"complete": True, "score": {"awarded": 14, "available": 20, "percent": 70}, "questions": []}


def attempt(lesson, **fields):
    return TestSubmission.objects.create(lesson=lesson, **fields)


class TestStates:
    @pytest.mark.parametrize(
        ("status", "open_"),
        [("generating", True), ("in_progress", True), ("grading", False), ("graded", False), ("failed", False)],
    )
    def test_an_attempt_is_open_only_while_it_is_generating_or_in_progress(self, lesson, status, open_):
        assert attempt(lesson, status=status).is_open is open_

    def test_the_newest_attempt_comes_first(self, lesson):
        for number in (1, 2, 3):
            attempt(lesson, attempt_no=number, status="graded")

        assert list(lesson.submissions.values_list("attempt_no", flat=True)) == [3, 2, 1]


class TestSeal:
    def sealed(self, lesson, status="graded", **fields):
        started = timezone.now() - timedelta(seconds=95)
        row = attempt(lesson, started_at=started, questions=[{"id": "t1"}])
        row.seal(
            answers={"t1": 1}, status=status, result=CARD, band="normal", followup=None, all_blank=False,
            now=started + timedelta(seconds=95), **fields,
        )  # fmt: skip
        return row

    def test_a_graded_attempt_stores_the_answers_the_marks_the_band_and_the_time_taken(self, lesson):
        row = self.sealed(lesson)

        assert row.status == "graded" and row.answers == {"t1": 1} and row.result == CARD
        assert (row.awarded, row.available, row.band, row.duration_s) == (14, 20, "normal", 95)
        assert row.submitted_at is not None and row.graded_at == row.submitted_at and row.followup is None

    def test_an_attempt_still_being_graded_has_no_marks_yet(self, lesson):
        row = self.sealed(lesson, status="grading")

        assert row.status == "grading" and (row.awarded, row.available, row.graded_at) == (None, None, None)
        assert row.submitted_at is not None

    def test_sealing_twice_changes_nothing_and_says_the_attempt_is_over(self, lesson):
        row = self.sealed(lesson)

        with pytest.raises(AttemptSealed):
            row.seal(
                answers={"t1": 3}, status="graded", result=CARD, band="fail", followup=None, all_blank=True,
                now=timezone.now(),
            )  # fmt: skip

        row.refresh_from_db()
        assert row.answers == {"t1": 1} and row.band == "normal" and row.all_blank is False

    def test_an_attempt_that_is_not_in_progress_cannot_be_sealed(self, lesson):
        row = attempt(lesson, status="generating")

        with pytest.raises(AttemptSealed):
            row.seal(
                answers={}, status="graded", result=CARD, band="fail", followup=None, all_blank=True,
                now=timezone.now(),
            )  # fmt: skip

        row.refresh_from_db()
        assert row.status == "generating" and row.submitted_at is None


def test_a_question_on_the_record_keeps_its_payload_and_goes_with_its_lesson(lesson):
    payload = {"id": "t1", "question": "Q?", "correct_index": 1}
    row = Question.objects.create(
        lesson=lesson, type="mcq", difficulty="easy", marks=1, payload=payload, stem_hash="f" * 64, concept="c"
    )

    row.refresh_from_db()
    assert row.payload == payload and row.retired is False and row.batch is None
    assert str(row) == "mcq question of Binary search"
    lesson.delete()
    assert not Question.objects.exists()


class TestFlowSettingsAdditions:
    def test_the_new_settings_have_the_documented_defaults(self):
        settings = FlowSettings.load()

        assert (settings.band_fail_below, settings.band_excellent_above) == (30, 90)
        assert (settings.question_batch_size, settings.batch_max_long, settings.batch_max_short) == (5, 1, 2)
        assert not hasattr(settings, "retakes_per_day")  # retired (T33): the hourly throttle is the limit

    def test_the_snapshot_carries_them_so_a_lesson_keeps_the_rules_it_started_with(self):
        snapshot = FlowSettings.load().snapshot()

        assert snapshot["band_fail_below"] == 30 and "retakes_per_day" not in snapshot

    def test_the_default_settings_are_valid(self):
        FlowSettings.load().full_clean()

    @pytest.mark.parametrize(("fail", "excellent"), [(90, 90), (95, 90), (100, 100)])
    def test_the_fail_line_must_be_below_the_excellent_line(self, fail, excellent):
        settings = FlowSettings(band_fail_below=fail, band_excellent_above=excellent)

        with pytest.raises(ValidationError) as caught:
            settings.full_clean()

        assert "band_fail_below" in caught.value.message_dict

    @pytest.mark.parametrize("size", [0, 4, 11, 100])
    def test_a_batch_is_five_to_ten_questions(self, size):
        with pytest.raises(ValidationError) as caught:
            FlowSettings(question_batch_size=size).full_clean()

        assert "question_batch_size" in caught.value.message_dict

    @pytest.mark.parametrize("size", [5, 7, 10])
    def test_a_batch_of_five_to_ten_is_accepted(self, size):
        FlowSettings(question_batch_size=size).full_clean()

    @pytest.mark.parametrize("percent", [101, 255])
    def test_a_percent_over_100_is_refused(self, percent):
        with pytest.raises(ValidationError):
            FlowSettings(band_excellent_above=percent).full_clean()
