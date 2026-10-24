from django.urls import path

from . import views

urlpatterns = [
    path("lessons", views.LessonListCreateView.as_view(), name="lessons"),
    path("lessons/<str:lesson_id>", views.LessonDetailView.as_view(), name="lesson-detail"),
    path("lessons/<str:lesson_id>/retry", views.LessonRetryView.as_view(), name="lesson-retry"),
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
    path("media/<str:asset_id>", views.MediaView.as_view(), name="media"),
    path("runs/<str:run_id>", views.RunView.as_view(), name="run"),
    path("runs/<str:run_id>/events", views.RunEventsView.as_view(), name="run-events"),
    path("runs/<str:run_id>/cancel", views.RunCancelView.as_view(), name="run-cancel"),
]
