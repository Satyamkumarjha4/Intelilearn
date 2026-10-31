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


class MaterialNotFound(LessonError):
    status_code = status.HTTP_404_NOT_FOUND
    default_code = "not_found"
    default_detail = "That study sheet does not exist (yet)."


class AlreadyExists(LessonError):
    """A sheet is never made twice. `extra.kinds` names the requested ones that exist, so the client opens them and asks
    only for the others."""

    status_code = status.HTTP_409_CONFLICT
    default_code = "already_exists"
    default_detail = "The lesson already has that study sheet."

    def __init__(self, kinds: list[str] | None = None):
        super().__init__()
        if kinds:
            self.extra = {"kinds": list(kinds)}


class FollowupExists(LessonError):
    """The follow-up of this level was already made. The client opens it: `extra.lesson_id` says which."""

    status_code = status.HTTP_409_CONFLICT
    default_code = "already_exists"
    default_detail = "That follow-up lesson already exists."

    def __init__(self, lesson_id):
        super().__init__()
        self.extra = {"lesson_id": str(lesson_id)}


class SheetsOnlyLesson(LessonError):
    """A follow-up grows out of a test result, and a lesson that is only study sheets has no test."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "sheets_only"
    default_detail = "This lesson is study sheets only, so it has no test to follow up on."


class StaleCodeVersion(LessonError):
    status_code = status.HTTP_409_CONFLICT
    default_code = "stale_code_version"
    default_detail = "The lesson changed since that error was reported. Reload it."


class RepairLimitReached(LessonError):
    status_code = status.HTTP_409_CONFLICT
    default_code = "repair_limit_reached"
    default_detail = "This lesson has already been repaired as often as allowed."


class VersionNotFound(LessonError):
    status_code = status.HTTP_404_NOT_FOUND
    default_code = "not_found"
    default_detail = "That version of the lesson does not exist."


class AlreadySubmitted(LessonError):
    status_code = status.HTTP_409_CONFLICT
    default_code = "already_submitted"
    default_detail = "The test has already been submitted. Its answers and score cannot be changed."

    def __init__(self, submission_id):
        super().__init__()
        self.extra = {"submission_id": str(submission_id)}


class NotFailed(LessonError):
    status_code = status.HTTP_409_CONFLICT
    default_code = "not_failed"
    default_detail = "Only a test whose grading failed can be graded again."


class SubmissionNotFound(LessonError):
    status_code = status.HTTP_404_NOT_FOUND
    default_code = "not_found"
    default_detail = "That attempt does not exist."


class AttemptInProgress(LessonError):
    """A start while an attempt is open returns that attempt; this is for what cannot share it."""

    status_code = status.HTTP_409_CONFLICT
    default_code = "attempt_in_progress"
    default_detail = "There is already an attempt in progress."


class AttemptSealed(LessonError):
    status_code = status.HTTP_409_CONFLICT
    default_code = "attempt_sealed"
    default_detail = "That attempt is over. Its answers and score cannot be changed."


class QuestionLocked(LessonError):
    status_code = status.HTTP_409_CONFLICT
    default_code = "locked"
    default_detail = "That question was already answered. Answers cannot be changed."


class RetakeLimitReached(LessonError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    default_code = "retake_limit"
    default_detail = "That is enough retakes for today. Try again tomorrow."
