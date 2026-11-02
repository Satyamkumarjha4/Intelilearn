"""Existing submissions become attempt 1, and every question the old tests asked goes on the record, retired.

Reversible: going back drops the record and the attempt columns (migration 0007 does that); nothing here is needed to
restore the original rows, which are never changed in a way their old shape cannot hold.
"""

from django.db import migrations

from graph.questions.dedupe import StemHash

DEFAULT_FAIL_BELOW, DEFAULT_EXCELLENT_ABOVE = 30, 90


def band_of(awarded: int, available: int, settings: dict) -> str:
    """The same rule as `graph.scoring.ScoreBand`, in whole marks (the migration must not depend on later code)."""
    if available <= 0:
        return ""
    if awarded * 100 < settings.get("band_fail_below", DEFAULT_FAIL_BELOW) * available:
        return "fail"
    if awarded * 100 > settings.get("band_excellent_above", DEFAULT_EXCELLENT_ABOVE) * available:
        return "excellent"
    return "normal"


def blank(answer) -> bool:
    return answer is None or (isinstance(answer, str) and not answer.strip()) or answer == []


def forwards(apps, schema_editor):
    Lesson = apps.get_model("lessons", "Lesson")
    Question = apps.get_model("lessons", "Question")
    Submission = apps.get_model("lessons", "TestSubmission")
    db = schema_editor.connection.alias  # the database being migrated, not the default

    for lesson in Lesson.objects.using(db).exclude(final_test__isnull=True).iterator():
        seen = set()
        for old in (lesson.final_test or {}).get("questions") or []:
            stem_hash = StemHash.of(old.get("question", ""))
            if stem_hash in seen:
                continue
            seen.add(stem_hash)
            Question.objects.using(db).create(
                lesson=lesson, type=old.get("type", ""), difficulty=old.get("difficulty", ""),
                concept=str(old.get("concept", ""))[:200], marks=old.get("marks") or 0, payload=old,
                stem_hash=stem_hash, batch=None, retired=True,
            )  # fmt: skip

    for submission in Submission.objects.using(db).select_related("lesson").iterator():
        lesson = submission.lesson
        questions = (lesson.final_test or {}).get("questions") or []
        update = {
            "attempt_no": 1,
            "questions": questions,
            "started_at": submission.submitted_at,
            "all_blank": bool(questions) and all(blank(submission.answers.get(q["id"])) for q in questions),
        }
        score = (submission.result or {}).get("score")
        if submission.status == "graded" and score:
            update |= {
                "awarded": score["awarded"],
                "available": score["available"],
                "band": band_of(score["awarded"], score["available"], lesson.settings_snapshot or {}),
            }
        Submission.objects.using(db).filter(pk=submission.pk).update(**update)


def backwards(apps, schema_editor):
    """Nothing to undo: the record and the attempt columns are dropped by migration 0007's reverse."""


class Migration(migrations.Migration):
    dependencies = [("lessons", "0007_attempts_question_record_and_settings")]

    operations = [migrations.RunPython(forwards, backwards)]
