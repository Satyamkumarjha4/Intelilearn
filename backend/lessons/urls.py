from django.urls import path

from . import views

urlpatterns = [
    path("lessons", views.LessonListCreateView.as_view(), name="lessons"),
    path("lessons/<str:lesson_id>", views.LessonDetailView.as_view(), name="lesson-detail"),
    path("lessons/<str:lesson_id>/retry", views.LessonRetryView.as_view(), name="lesson-retry"),
    path("lessons/<str:lesson_id>/followups", views.FollowupView.as_view(), name="lesson-followups"),
    path("lessons/<str:lesson_id>/quizzes/<str:kind>", views.QuizView.as_view(), name="quiz"),
    path("lessons/<str:lesson_id>/quizzes/<str:kind>/attempt", views.QuizAttemptView.as_view(), name="quiz-attempt"),
    path("lessons/<str:lesson_id>/quizzes/<str:kind>/review", views.QuizReviewView.as_view(), name="quiz-review"),
    path("lessons/<str:lesson_id>/choice", views.MaterialChoiceView.as_view(), name="material-choice"),
    path("lessons/<str:lesson_id>/materials", views.MaterialRequestView.as_view(), name="material-request"),
    path(
        "lessons/<str:lesson_id>/materials/practice_sheet/grade",
        views.PracticeGradeView.as_view(),
        name="practice-grade",
    ),
    path("lessons/<str:lesson_id>/materials/<str:kind>", views.MaterialView.as_view(), name="material"),
    path("lessons/<str:lesson_id>/document", views.LessonDocumentView.as_view(), name="lesson-document"),
    path("lessons/<str:lesson_id>/repair", views.LessonRepairView.as_view(), name="lesson-repair"),
    path("lessons/<str:lesson_id>/versions", views.LessonVersionsView.as_view(), name="lesson-versions"),
    path(
        "lessons/<str:lesson_id>/versions/<int:number>/restore",
        views.LessonVersionRestoreView.as_view(),
        name="lesson-version-restore",
    ),
    path("lessons/<str:lesson_id>/test", views.LessonTestView.as_view(), name="lesson-test"),
    path("lessons/<str:lesson_id>/test/attempts", views.AttemptsView.as_view(), name="test-attempts"),
    path("lessons/<str:lesson_id>/test/attempts/<str:attempt_id>", views.AttemptView.as_view(), name="test-attempt"),
    path(
        "lessons/<str:lesson_id>/test/attempts/<str:attempt_id>/answers/<str:question_id>",
        views.AttemptAnswerView.as_view(),
        name="test-attempt-answer",
    ),
    path(
        "lessons/<str:lesson_id>/test/attempts/<str:attempt_id>/submit",
        views.AttemptSubmitView.as_view(),
        name="test-attempt-submit",
    ),
    path(
        "lessons/<str:lesson_id>/test/attempts/<str:attempt_id>/regrade",
        views.AttemptRegradeView.as_view(),
        name="test-attempt-regrade",
    ),
    path(
        "lessons/<str:lesson_id>/test/submission",
        views.TestSubmissionCurrentView.as_view(),
        name="test-submission-current",
    ),
    path(
        "lessons/<str:lesson_id>/test/submissions/<str:submission_id>",
        views.TestSubmissionView.as_view(),
        name="test-submission",
    ),
    path("media/<str:asset_id>", views.MediaView.as_view(), name="media"),
    path("runs/<str:run_id>", views.RunView.as_view(), name="run"),
    path("runs/<str:run_id>/events", views.RunEventsView.as_view(), name="run-events"),
    path("runs/<str:run_id>/cancel", views.RunCancelView.as_view(), name="run-cancel"),
]
