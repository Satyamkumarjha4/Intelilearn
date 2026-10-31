from django.urls import path

from . import views

urlpatterns = [
    path("quick-quizzes", views.QuizListCreateView.as_view(), name="quizzes"),
    path("quick-quizzes/topic-traits", views.TopicTraitsView.as_view(), name="quiz-topic-traits"),
    path("quick-quizzes/<str:quiz_id>", views.QuizDetailView.as_view(), name="quiz-detail"),
    path("quick-quizzes/<str:quiz_id>/calibration", views.CalibrationView.as_view(), name="quiz-calibration"),
    path(
        "quick-quizzes/<str:quiz_id>/calibration/answer",
        views.CalibrationAnswerView.as_view(),
        name="quiz-calibration-answer",
    ),
    path("quick-quizzes/<str:quiz_id>/attempts", views.QuizAttemptsView.as_view(), name="quiz-attempts"),
    path("quick-quizzes/<str:quiz_id>/attempts/<str:attempt_id>", views.QuizAttemptView.as_view(), name="quiz-attempt"),
    path(
        "quick-quizzes/<str:quiz_id>/attempts/<str:attempt_id>/answers/<str:question_id>",
        views.QuizAttemptAnswerView.as_view(),
        name="quiz-attempt-answer",
    ),
    path(
        "quick-quizzes/<str:quiz_id>/attempts/<str:attempt_id>/submit",
        views.QuizAttemptSubmitView.as_view(),
        name="quiz-attempt-submit",
    ),
    path(
        "quick-quizzes/<str:quiz_id>/attempts/<str:attempt_id>/regrade",
        views.QuizAttemptRegradeView.as_view(),
        name="quiz-attempt-regrade",
    ),
    path("quick-quizzes/<str:quiz_id>/create-lesson", views.QuizCreateLessonView.as_view(), name="quiz-create-lesson"),
]
