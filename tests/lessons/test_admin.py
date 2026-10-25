"""Unit under test: `lessons.admin`: the admin screens for lessons, runs, quizzes and the flow settings.

Why: the admin is where an operator inspects a failed lesson and edits the thresholds every new lesson snapshots. A
changelist that fails to render hides the failure; a second FlowSettings row, or a deleted one, would break the
singleton that `FlowSettings.load()` relies on.

Use cases:
- each lessons changelist renders, and the lesson page shows its runs
- the test submissions changelist shows each score as marks earned over marks available, and is blank before grading
- the lesson changelist shows the error of a failed lesson
- there can be only one FlowSettings row, and it cannot be deleted
- editing the flow settings changes what the next lesson snapshots
"""

import pytest
from django.urls import reverse

from lessons.models import FlowSettings, GraphRun, Lesson, Quiz, QuizAttempt, Stage, StudyMaterial, TestSubmission

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    "model",
    [
        "lesson",
        "graphrun",
        "quiz",
        "quizattempt",
        "studymaterial",
        "mediaasset",
        "lessonversion",
        "testsubmission",
        "flowsettings",
    ],
)
def test_changelists_render(admin_client, lesson, model):
    quiz = Quiz.objects.create(lesson=lesson, kind="diagnostic", questions=[])
    QuizAttempt.objects.create(quiz=quiz, answers={}, result={"correct": 3, "total": 10})
    StudyMaterial.objects.create(lesson=lesson, kind="cheat_sheet", content={})
    GraphRun.objects.create(lesson=lesson, trigger=GraphRun.Trigger.START)
    FlowSettings.load()

    response = admin_client.get(reverse(f"admin:lessons_{model}_changelist"))

    assert response.status_code == 200


def test_the_lesson_page_shows_its_runs(admin_client, lesson):
    GraphRun.objects.create(lesson=lesson, trigger=GraphRun.Trigger.START, status=GraphRun.Status.PAUSED)

    response = admin_client.get(reverse("admin:lessons_lesson_change", args=[lesson.pk]))

    assert response.status_code == 200 and "paused" in response.content.decode()


def test_the_changelist_shows_the_error_of_a_failed_lesson(admin_client, lesson):
    Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.FAILED, error="The model refused to answer.")

    response = admin_client.get(reverse("admin:lessons_lesson_changelist"))

    assert "The model refused to answer." in response.content.decode()


def test_the_flow_settings_cannot_get_a_second_row_or_be_deleted(admin_client):
    settings = FlowSettings.load()

    add = admin_client.get(reverse("admin:lessons_flowsettings_add"))
    delete = admin_client.post(reverse("admin:lessons_flowsettings_delete", args=[settings.pk]), {"post": "yes"})

    assert add.status_code == 403 and delete.status_code == 403
    assert FlowSettings.objects.count() == 1


def test_editing_the_flow_settings_changes_the_next_snapshot(admin_client):
    settings = FlowSettings.load()
    form = {name: value for name, value in FlowSettings.load().snapshot().items() if not isinstance(value, list)}
    form |= {"prereq_trigger_max_correct": 1, "media_sources": '["wikimedia"]', "allowed_media_licenses": '["cc0"]'}
    form = {k: ("on" if v is True else v) for k, v in form.items() if v is not False}

    response = admin_client.post(reverse("admin:lessons_flowsettings_change", args=[settings.pk]), form)

    assert response.status_code == 302
    assert FlowSettings.load().snapshot()["prereq_trigger_max_correct"] == 1


def test_the_submissions_changelist_shows_the_score(admin_client, lesson):
    TestSubmission.objects.create(lesson=lesson, result={"score": {"awarded": 14, "available": 20}}, status="graded")

    response = admin_client.get(reverse("admin:lessons_testsubmission_changelist"))

    assert response.status_code == 200 and "14/20" in response.content.decode()
