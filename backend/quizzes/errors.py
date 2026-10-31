"""Why a quick quiz request was refused. Each is an `APIException`, so the API turns it into `{detail, code}` itself.
Most refusals reuse the lessons' errors (`WrongStage`, `AttemptSealed`, `QuestionLocked`…); these are the quiz's own."""

from rest_framework import status

from lessons.errors import LessonError


class SourceNotUsable(LessonError):
    """A lesson that cannot be asked about: it is only study sheets, or its pages are not written yet."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "source_not_usable"
    default_detail = "That lesson cannot be used for a quiz."

    def __init__(self, detail=None, *, lesson_id=None):
        super().__init__(detail)
        self.extra = {"fields": {"source": [str(self.detail)]}, **({"lesson_id": str(lesson_id)} if lesson_id else {})}


class SourceMissing(LessonError):
    """A lesson the quiz was made from has been deleted, so there is nothing to write new questions from."""

    status_code = status.HTTP_409_CONFLICT
    default_code = "source_missing"
    default_detail = "A lesson this quiz was made from has been deleted, so the quiz cannot be taken again."


class NoQuestionLeft(LessonError):
    status_code = status.HTTP_409_CONFLICT
    default_code = "calibration_over"
    default_detail = "The calibration quiz is over."


class NotTheCurrentQuestion(LessonError):
    status_code = status.HTTP_409_CONFLICT
    default_code = "not_current"
    default_detail = "That is not the question you are on."


class NoTopicQuiz(LessonError):
    """A lesson can only grow out of a quiz about a topic: a quiz from lessons points at those lessons instead."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "not_a_topic_quiz"
    default_detail = "Only a quiz about a topic can become a lesson. Study the lessons it was made from instead."
