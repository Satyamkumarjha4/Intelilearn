"""Unit under test: lessons migrations 0007 (`attempts_question_record_and_settings`), 0008 (`attempt_backfill`) and
0010 (`many_attempts_per_lesson`), which turn "the" test submission into an attempt, write the record of questions and
finally let a lesson have more than one.

Why: they rewrite real learners' results. After them every existing submission must be attempt 1 with the questions it
was answered against and the marks it scored, every question the old tests ever asked must be on the record (retired, so
a retake never repeats an old stem), and the whole thing must be undoable.

Use cases:
- an existing submission becomes attempt 1: its questions are copied from the lesson's old test, it started when it was
  submitted, and a graded one gets awarded, available and band from its score card
- a submission still being graded gets no marks yet, and an all-blank one is flagged
- every question of every old test becomes a retired Question row, once even if the test repeats a stem
- a lesson with no submission and no test, and a lesson with a test but no submission, get no attempt
- the new settings have their defaults on the existing settings row
- the migrations can be undone: the record and the attempt columns go, and the original rows are as they were
- the constraints hold: one attempt number per lesson, at most one open attempt, one stem per lesson in the record
- the last migration lets a lesson have many attempts; undoing it keeps the first attempt of each lesson and deletes the
  retakes and any open attempt, so the old constraint can come back
"""

import pytest
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor

BEFORE = [("lessons", "0006_level_and_difficulty_names")]
AFTER = [("lessons", "0008_attempt_backfill")]
NINE = [("lessons", "0009_graphrun_retake_choices")]
TEN = [("lessons", "0010_many_attempts_per_lesson")]


def latest():
    return list(MigrationExecutor(connection).loader.graph.leaf_nodes("lessons"))


def migrate(targets):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)
    return MigrationExecutor(connection).loader.project_state(targets).apps


def question(number, text=None, kind="mcq", marks=2):
    return {
        "id": f"t{number}", "type": kind, "difficulty": "standard", "concept": f"Concept {number}", "marks": marks,
        "question": text or f"Question number {number}?", "options": ["a", "b", "c", "d"], "correct_index": 1,
    }  # fmt: skip


TEST = {"title": "T", "questions": [question(1), question(2), question(3, kind="short_answer")]}
CARD = {"complete": True, "score": {"awarded": 5, "available": 6, "percent": 83}, "questions": []}


@pytest.mark.django_db(transaction=True)
def test_a_submission_becomes_attempt_one_and_every_old_question_goes_on_the_record(django_user_model):
    old = migrate(BEFORE)
    Lesson, Submission = old.get_model("lessons", "Lesson"), old.get_model("lessons", "TestSubmission")
    owner = django_user_model.objects.create_user("m@example.com", password="x", name="M")
    graded = Lesson.objects.create(owner_id=owner.pk, topic="Graded", stage="ready", final_test=TEST)
    grading = Lesson.objects.create(owner_id=owner.pk, topic="Grading", stage="ready", final_test=TEST)
    blank = Lesson.objects.create(owner_id=owner.pk, topic="Blank", stage="ready", final_test=TEST)
    untaken = Lesson.objects.create(owner_id=owner.pk, topic="Untaken", stage="ready", final_test=TEST)
    bare = Lesson.objects.create(owner_id=owner.pk, topic="Bare", stage="failed")
    repeated = Lesson.objects.create(
        owner_id=owner.pk, topic="Repeated", final_test={"questions": [question(1, "Same?"), question(2, "same")]}
    )
    first = Submission.objects.create(lesson_id=graded.pk, answers={"t1": 1, "t2": 0}, result=CARD, status="graded")
    pending = Submission.objects.create(
        lesson_id=grading.pk, answers={"t1": 1}, result={**CARD, "complete": False}, status="grading"
    )
    empty = Submission.objects.create(lesson_id=blank.pk, answers={"t1": None, "t2": "  ", "t3": []}, status="graded")
    empty.result = {**CARD, "score": {"awarded": 0, "available": 6, "percent": 0}}
    empty.save()
    submitted = {s.pk: s.submitted_at for s in Submission.objects.all()}

    try:
        new = migrate(AFTER)
        Submission, Question = new.get_model("lessons", "TestSubmission"), new.get_model("lessons", "Question")

        one = Submission.objects.get(pk=first.pk)
        assert one.attempt_no == 1 and one.questions == TEST["questions"] and one.started_at == submitted[first.pk]
        assert (one.awarded, one.available, one.band, one.all_blank) == (5, 6, "normal", False)
        assert one.status == "graded" and one.answers == {"t1": 1, "t2": 0} and one.submitted_at == submitted[first.pk]

        waiting = Submission.objects.get(pk=pending.pk)
        assert (waiting.awarded, waiting.available, waiting.band) == (None, None, "")

        zero = Submission.objects.get(pk=empty.pk)
        assert zero.all_blank is True and (zero.awarded, zero.band) == (0, "fail")

        assert not Submission.objects.filter(lesson_id__in=[untaken.pk, bare.pk]).exists()
        rows = Question.objects.filter(lesson_id=graded.pk).order_by("created_at", "payload__id")
        assert sorted(r.payload["id"] for r in rows) == ["t1", "t2", "t3"]
        assert all(r.retired and r.batch is None for r in rows) and len({r.stem_hash for r in rows}) == 3
        assert {(r.type, r.difficulty, r.marks) for r in rows} == {
            ("mcq", "standard", 2),
            ("short_answer", "standard", 2),
        }
        assert Question.objects.filter(lesson_id=untaken.pk).count() == 3  # asked, even though never answered
        assert Question.objects.filter(lesson_id=bare.pk).count() == 0
        assert Question.objects.filter(lesson_id=repeated.pk).count() == 1  # one stem, once
    finally:
        migrate(latest())


@pytest.mark.django_db(transaction=True)
def test_the_new_settings_have_their_defaults_on_the_existing_row():
    old = migrate(BEFORE)
    old.get_model("lessons", "FlowSettings").objects.create(pk=1)

    try:
        new = migrate(AFTER)
        row = new.get_model("lessons", "FlowSettings").objects.get(pk=1)

        assert (row.band_fail_below, row.band_excellent_above, row.question_batch_size) == (30, 90, 5)
        assert (row.batch_max_long, row.batch_max_short, row.retakes_per_day) == (1, 2, 3)
    finally:
        migrate(latest())


@pytest.mark.django_db(transaction=True)
def test_the_migrations_can_be_undone(django_user_model):
    old = migrate(BEFORE)
    Lesson, Submission = old.get_model("lessons", "Lesson"), old.get_model("lessons", "TestSubmission")
    owner = django_user_model.objects.create_user("u@example.com", password="x", name="U")
    lesson = Lesson.objects.create(owner_id=owner.pk, topic="T", stage="ready", final_test=TEST)
    original = Submission.objects.create(lesson_id=lesson.pk, answers={"t1": 1}, result=CARD, status="graded")

    try:
        migrate(AFTER)
        back = migrate(BEFORE)
        restored = back.get_model("lessons", "TestSubmission").objects.get(pk=original.pk)

        assert restored.answers == {"t1": 1} and restored.status == "graded" and restored.submitted_at is not None
        assert "Question" not in {m.__name__ for m in back.get_models() if m._meta.app_label == "lessons"}
        assert not hasattr(restored, "attempt_no")
    finally:
        migrate(latest())


@pytest.mark.django_db(transaction=True)
def test_the_constraints_keep_attempt_numbers_open_attempts_and_stems_unique(django_user_model):
    apps = migrate(AFTER)  # the models as they were then: the lesson table has fewer columns now
    try:
        Lesson, Question = apps.get_model("lessons", "Lesson"), apps.get_model("lessons", "Question")
        TestSubmission = apps.get_model("lessons", "TestSubmission")

        owner = django_user_model.objects.create_user("c@example.com", password="x", name="C")
        lesson = Lesson.objects.create(owner_id=owner.pk, topic="T")
        TestSubmission.objects.create(lesson=lesson, attempt_no=1, status="graded")

        with pytest.raises(IntegrityError), transaction.atomic():
            TestSubmission.objects.create(lesson=lesson, attempt_no=1, status="graded")
        TestSubmission.objects.filter(lesson=lesson).delete()
        TestSubmission.objects.create(lesson=lesson, attempt_no=1, status="in_progress")
        with pytest.raises(IntegrityError), transaction.atomic():
            TestSubmission.objects.create(lesson=lesson, attempt_no=2, status="generating")

        Question.objects.create(lesson=lesson, type="mcq", difficulty="easy", marks=1, payload={}, stem_hash="a" * 64)
        with pytest.raises(IntegrityError), transaction.atomic():
            Question.objects.create(
                lesson=lesson, type="mcq", difficulty="easy", marks=1, payload={}, stem_hash="a" * 64
            )
    finally:
        migrate(latest())


@pytest.mark.django_db(transaction=True)
def test_a_lesson_can_have_many_attempts_and_going_back_keeps_the_first(django_user_model):
    old = migrate(NINE)
    Lesson, Submission = old.get_model("lessons", "Lesson"), old.get_model("lessons", "TestSubmission")
    owner = django_user_model.objects.create_user("t@example.com", password="x", name="T")
    lesson = Lesson.objects.create(owner_id=owner.pk, topic="T", stage="ready")
    one = Submission.objects.create(lesson_id=lesson.pk, attempt_no=1, status="graded")
    with pytest.raises(IntegrityError), transaction.atomic():  # the old rule: a lesson has one submission
        Submission.objects.create(lesson_id=lesson.pk, attempt_no=2, status="graded")

    try:
        new = migrate(TEN)
        Submission = new.get_model("lessons", "TestSubmission")
        Submission.objects.create(lesson_id=lesson.pk, attempt_no=2, status="graded")
        Submission.objects.create(lesson_id=lesson.pk, attempt_no=3, status="in_progress")
        assert Submission.objects.filter(lesson_id=lesson.pk).count() == 3

        back = migrate(NINE)

        kept = back.get_model("lessons", "TestSubmission").objects.filter(lesson_id=lesson.pk)
        assert [row.pk for row in kept] == [one.pk]
        with pytest.raises(IntegrityError), transaction.atomic():
            back.get_model("lessons", "TestSubmission").objects.create(
                lesson_id=lesson.pk, attempt_no=2, status="graded"
            )
    finally:
        migrate(latest())
