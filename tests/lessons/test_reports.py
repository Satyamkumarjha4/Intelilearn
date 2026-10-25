"""Unit under test: `lessons.reports.LessonReport`, the plain-text report behind `manage.py flow show`.

Why: it is what an operator reads to judge a lesson. A section that crashes on a lesson at an early stage, or that
hides an error, makes the report useless exactly when something is wrong.

Use cases:
- the header names the topic, owner, stage, route, level, the learner's context and any error
- quiz scores are listed with the per-band breakdown, and an inconsistent result is flagged
- the assessment lists the level, start point, knowledge, gaps and the prerequisites to cover
- the plan, the pages and the test are summarised, with the prerequisites the introduction covers
- the interactives are listed as built, media or dropped, with the media's source, licence and attribution
- the study sheets are listed with their title and size
- warnings and recent runs are listed
- a brand-new lesson reports without error and without empty sections
"""

import pytest

from graph.grading import QuizGrader
from lessons.models import GraphRun, Lesson, MediaAsset, Quiz, QuizAttempt, Stage
from lessons.reports import LessonReport

pytestmark = pytest.mark.django_db


def text(lesson) -> str:
    lesson.refresh_from_db()
    return "\n".join(LessonReport().lines(lesson))


def test_a_new_lesson_reports_without_empty_sections(lesson):
    report = text(lesson)

    assert "Binary search" in report and "stage: preparing_diagnostic" in report and "route: -" in report
    assert "assessment" not in report and "warnings" not in report and "runs:" not in report


def test_the_header_shows_the_context_and_the_error(lesson):
    Lesson.objects.filter(pk=lesson.pk).update(
        user_context="for my exam", stage=Stage.FAILED, error="The model refused."
    )

    report = text(lesson)

    assert "owner: ada@example.com" in report and "context: for my exam" in report
    assert "ERROR: The model refused." in report


def test_quiz_scores_are_listed_with_bands_and_inconsistency_is_flagged(lesson):
    from support.quiz_data import make_questions

    questions = make_questions()
    hard_only = {
        q["id"]: q["correct_index"] if q["band"] == "hard" else (q["correct_index"] + 1) % 4 for q in questions
    }
    quiz = Quiz.objects.create(lesson=lesson, kind="diagnostic", questions=questions)
    QuizAttempt.objects.create(quiz=quiz, answers=hard_only, result=QuizGrader().grade(questions, hard_only).as_dict())

    report = text(lesson)

    assert "diagnostic quiz: 2/10 correct, 0 don't know" in report and "hard 2/2" in report
    assert "possible guessing" in report


def test_the_assessment_is_summarised(lesson):
    Lesson.objects.filter(pk=lesson.pk).update(
        assessment={"level": "beginner", "confidence": "high", "start_point": "Halving",
                    "known_concepts": ["Lists"], "gaps": ["Invariants", "Pointers"]},
        prerequisites_to_cover=[{"name": "Arrays", "why_needed": "x"}],
    )  # fmt: skip

    report = text(lesson)

    assert "assessment: beginner (confidence high)" in report and "start at: Halving" in report
    assert "knows: Lists" in report and "gaps: Invariants, Pointers" in report
    assert "prerequisites to cover: Arrays" in report


def test_warnings_and_runs_are_listed(lesson):
    Lesson.objects.filter(pk=lesson.pk).update(warnings=["Dropped a widget"])
    GraphRun.objects.create(lesson=lesson, trigger=GraphRun.Trigger.START, status=GraphRun.Status.PAUSED)

    report = text(lesson)

    assert "- Dropped a widget" in report and "flow/start: paused" in report


def test_study_sheets_are_listed_with_their_size(lesson):
    from support.study_data import make_cheat_sheet, make_practice_sheet, make_revision_sheet

    from lessons.models import StudyMaterial

    StudyMaterial.objects.create(lesson=lesson, kind="cheat_sheet", content=make_cheat_sheet())
    StudyMaterial.objects.create(lesson=lesson, kind="revision_sheet", content=make_revision_sheet())
    StudyMaterial.objects.create(lesson=lesson, kind="practice_sheet", content=make_practice_sheet())

    report = text(lesson)

    assert "cheat_sheet: Binary search cheat sheet (7 items in 2 sections)" in report
    assert "revision_sheet: Binary search revision (4 subtopics)" in report
    assert "practice_sheet: Binary search practice (15 questions)" in report


def test_the_plan_the_pages_and_the_test_are_summarised(lesson):
    from support.lesson_data import make_final_test, make_pages, make_plan

    Lesson.objects.filter(pk=lesson.pk).update(
        plan=make_plan(prerequisites=["Arrays"]), pages=make_pages(), final_test=make_final_test()
    )

    report = text(lesson)

    assert "plan: Binary search (beginner)" in report
    assert "introduction: Searching a list, Sorted data, Why halving helps [prerequisites: Arrays]" in report
    assert "test: 10 questions (4 mcq, 2 numerical, 2 short_answer, 1 long_answer, 1 code)" in report
    assert "page core: Core page: 3 sections," in report and "(Halving the range; The loop invariant;" in report


def test_interactives_are_listed_as_built_media_or_dropped_with_the_medias_credit(lesson):
    from support.lesson_data import make_interactive_plan

    plan = make_interactive_plan()
    plan["specs"][0]["kind"] = "image"
    plan["specs"][2]["dropped"] = True
    Lesson.objects.filter(pk=lesson.pk).update(interactive_plan=plan)
    MediaAsset.objects.create(
        lesson=lesson, spec_id="widget_introduction", kind="image", file="x.png", mime_type="image/png", width=400,
        height=300, source="wikimedia", license="cc-by-sa", attribution="Jane Doe", verified=True,
    )  # fmt: skip

    report = text(lesson)

    assert "widget_introduction (introduction, image, media)" in report
    assert (
        "widget_core (core, simulation, built)" in report
        and "widget_advanced (advanced, svg_diagram, dropped)" in report
    )
    assert "media widget_introduction: image 400x300 from wikimedia, cc-by-sa, by Jane Doe, verified" in report
