"""Unit under test: lessons migration 0019 (`first_set_backfill`), which moves every lesson's test out of
`Lesson.final_test` and onto the record of questions as its "first set", so the column can be dropped.

Why: `Lesson.final_test` held the questions attempt 1 serves. Without it a lesson that nobody has taken the test of yet
would have no test, and a learner who opens it would find an empty page. So before the column goes, every question of
every old test must have a row on the record, in its place in the set, with its answer key, and a legacy lesson that has
never been attempted must be able to serve it (its rows are not withdrawn). The step must undo itself, so a release can
be rolled back, and must not touch a lesson's attempts.

Use cases:
- a legacy lesson with a test and no attempt: its questions become the first set in order, each with a row (made if it
  has none), the full question kept as it was, and the rows are no longer withdrawn
- a lesson made after the record existed: its questions are found by their row ids and flagged, and the rows are not
  changed otherwise
- a lesson that has an attempt: its rows get their places too (a report reads them), but stay withdrawn if they
  were, and the attempt is untouched
- two questions with the same stem are one row, in the place of the first
- a lesson with no test gets nothing
- running it again changes nothing
- undoing it writes `final_test` back from the first set for every lesson that has one, with the row ids
"""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

BEFORE = [("lessons", "0018_question_first_set")]
AFTER = [("lessons", "0019_first_set_backfill")]


def latest():
    return list(MigrationExecutor(connection).loader.graph.leaf_nodes())


def migrate(targets):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)
    return MigrationExecutor(connection).loader.project_state(targets).apps


def question(number, text=None, **extra):
    return {
        "id": f"t{number}", "type": "mcq", "difficulty": "standard", "concept": f"Concept {number}", "marks": 2,
        "question": text or f"Question number {number}?", "options": ["a", "b", "c", "d"], "correct_index": 1, **extra,
    }  # fmt: skip


def stem(text):
    from graph.questions.dedupe import StemHash

    return StemHash.of(text)


@pytest.fixture
def owner(django_user_model):
    return django_user_model.objects.create_user("first-set@example.com", password="x", name="F")


@pytest.fixture
def before():
    apps = migrate(BEFORE)
    yield apps
    migrate(latest())  # leave the database at the latest state, whatever migration has been added since


pytestmark = pytest.mark.django_db(transaction=True)


def row(Question, lesson, number, *, retired, text=None, batch=None):
    q = question(number, text)
    return Question.objects.create(
        lesson_id=lesson.pk, type="mcq", difficulty="standard", concept=q["concept"], marks=2, payload=q,
        stem_hash=stem(q["question"]), retired=retired, batch=batch,
    )  # fmt: skip


def test_a_legacy_lesson_with_no_attempt_gets_its_test_as_the_first_set(before, owner):
    Lesson, Question = before.get_model("lessons", "Lesson"), before.get_model("lessons", "Question")
    questions = [question(1), question(2), question(3)]
    lesson = Lesson.objects.create(
        owner_id=owner.pk, topic="Old", stage="ready", final_test={"title": "T", "questions": questions}
    )
    for number in (1, 2):  # migration 0008 wrote these, withdrawn
        row(Question, lesson, number, retired=True)
    # the third question has no row at all

    new = migrate(AFTER)

    Question = new.get_model("lessons", "Question")
    rows = list(Question.objects.filter(lesson_id=lesson.pk).order_by("first_set_position"))
    assert [r.first_set_position for r in rows] == [0, 1, 2]
    assert [r.payload for r in rows] == questions
    assert [r.retired for r in rows] == [False, False, False]


def test_a_lesson_made_after_the_record_existed_is_found_by_its_row_ids(before, owner):
    Lesson, Question = before.get_model("lessons", "Lesson"), before.get_model("lessons", "Question")
    lesson = Lesson.objects.create(owner_id=owner.pk, topic="New", stage="ready")
    rows = [row(Question, lesson, n, retired=False, batch="11111111-1111-1111-1111-111111111111") for n in (1, 2)]
    served = [{**question(n), "question_id": str(r.id)} for n, r in enumerate(rows, 1)]
    Lesson.objects.filter(pk=lesson.pk).update(final_test={"title": "T", "questions": served})

    new = migrate(AFTER)

    Question = new.get_model("lessons", "Question")
    after = list(Question.objects.filter(lesson_id=lesson.pk).order_by("first_set_position"))
    assert [str(r.id) for r in after] == [str(r.id) for r in rows]
    assert [r.first_set_position for r in after] == [0, 1] and Question.objects.filter(lesson_id=lesson.pk).count() == 2
    assert [r.payload for r in after] == [question(1), question(2)]  # the row's own payload, not the served copy


def test_a_lesson_with_an_attempt_keeps_its_rows_withdrawn_and_its_attempt_as_it_was(before, owner):
    Lesson, Question, Submission = (before.get_model("lessons", n) for n in ("Lesson", "Question", "TestSubmission"))
    questions = [question(1), question(2)]
    lesson = Lesson.objects.create(owner_id=owner.pk, topic="Taken", stage="ready", final_test={"questions": questions})
    for number in (1, 2):
        row(Question, lesson, number, retired=True)
    attempt = Submission.objects.create(
        lesson_id=lesson.pk, attempt_no=1, status="graded", questions=questions, answers={}
    )

    new = migrate(AFTER)

    Question, Submission = new.get_model("lessons", "Question"), new.get_model("lessons", "TestSubmission")
    rows = list(Question.objects.filter(lesson_id=lesson.pk).order_by("first_set_position"))
    assert [r.first_set_position for r in rows] == [0, 1] and [r.retired for r in rows] == [True, True]
    assert Submission.objects.get(pk=attempt.pk).questions == questions


def test_two_questions_with_one_stem_are_one_row_in_the_place_of_the_first(before, owner):
    Lesson = before.get_model("lessons", "Lesson")
    same = [question(1, "Same?"), question(2, "same"), question(3)]
    lesson = Lesson.objects.create(owner_id=owner.pk, topic="Twice", stage="ready", final_test={"questions": same})

    new = migrate(AFTER)

    Question = new.get_model("lessons", "Question")
    rows = list(
        Question.objects.filter(lesson_id=lesson.pk, first_set_position__isnull=False).order_by("first_set_position")
    )
    assert [r.payload["id"] for r in rows] == ["t1", "t3"] and [r.first_set_position for r in rows] == [0, 1]


def test_a_lesson_with_no_test_gets_nothing(before, owner):
    Lesson = before.get_model("lessons", "Lesson")
    bare = Lesson.objects.create(owner_id=owner.pk, topic="Bare", stage="failed")

    new = migrate(AFTER)

    assert new.get_model("lessons", "Question").objects.filter(lesson_id=bare.pk).count() == 0


def test_running_it_again_changes_nothing(before, owner):
    Lesson = before.get_model("lessons", "Lesson")
    lesson = Lesson.objects.create(
        owner_id=owner.pk, topic="Old", stage="ready", final_test={"questions": [question(1), question(2)]}
    )
    migrate(AFTER)
    from lessons.first_sets import FirstSetBackfill

    new = MigrationExecutor(connection).loader.project_state(AFTER).apps
    Question = new.get_model("lessons", "Question")
    first = list(
        Question.objects.filter(lesson_id=lesson.pk).order_by("id").values_list("id", "first_set_position", "retired")
    )

    FirstSetBackfill().forward(new)

    assert (
        list(
            Question.objects.filter(lesson_id=lesson.pk)
            .order_by("id")
            .values_list("id", "first_set_position", "retired")
        )
        == first
    )


def test_undoing_it_writes_the_test_back_from_the_first_set(before, owner):
    Lesson = before.get_model("lessons", "Lesson")
    questions = [question(1), question(2), question(3)]
    lesson = Lesson.objects.create(
        owner_id=owner.pk, topic="Old", stage="ready", final_test={"title": "T", "questions": questions}
    )
    migrate([("lessons", "0020_contract_final_test")])  # the column is gone, as after the release

    old = migrate(BEFORE)  # and comes back empty, then 0019 writes it again

    stored = old.get_model("lessons", "Lesson").objects.get(pk=lesson.pk).final_test
    assert [q["question"] for q in stored["questions"]] == [q["question"] for q in questions]
    assert [q["id"] for q in stored["questions"]] == ["t1", "t2", "t3"] and all(
        q["question_id"] for q in stored["questions"]
    )
