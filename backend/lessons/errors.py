"""Why a lessons request was refused. Each is an `APIException`, so the API turns it into `{detail, code}` itself."""

from rest_framework import status
from rest_framework.exceptions import APIException


class LessonError(APIException):
    pass


class LessonNotConfigured(LessonError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_code = "llm_not_configured"
    default_detail = "The tutor is not set up yet."


class WrongStage(LessonError):
    status_code = status.HTTP_409_CONFLICT
    default_code = "wrong_stage"
    default_detail = "The lesson is not in a stage where that can be done."


class RunInProgress(LessonError):
    status_code = status.HTTP_409_CONFLICT
    default_code = "run_in_progress"
    default_detail = "The lesson is still being worked on. Try again in a moment."


class AlreadyAttempted(LessonError):
    status_code = status.HTTP_409_CONFLICT
    default_code = "already_attempted"
    default_detail = "This quiz was already answered."


class NotAttempted(LessonError):
    status_code = status.HTTP_409_CONFLICT
    default_code = "not_attempted"
    default_detail = "Answer the quiz first; the review shows the correct answers."


class QuizNotFound(LessonError):
    status_code = status.HTTP_404_NOT_FOUND
    default_code = "not_found"
    default_detail = "That quiz does not exist (yet)."


class InvalidAnswers(LessonError):
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "invalid_answers"
    default_detail = "The answers do not fit the quiz."


class QueueUnavailable(LessonError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_code = "queue_unavailable"
    default_detail = "The background worker queue is unreachable. Nothing was lost: try again in a moment."


class RunEnded(LessonError):
    status_code = status.HTTP_409_CONFLICT
    default_code = "run_ended"
    default_detail = "That run has already ended."
