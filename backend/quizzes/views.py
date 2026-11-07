"""Thin views for the quick quiz API: parse, call a service, format. Every query starts from the requesting user's own
quizzes (`QuickQuiz.objects.owned_by`), so another learner's quiz, attempt or calibration is a 404, never a 403."""

from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from lessons.idempotency import IdempotentRequest
from lessons.serializers import LessonCreatedSerializer
from lessons.views import IDEMPOTENCY_KEY, LessonCursorPagination, parse_id

from .attempts import QuizAttemptService
from .models import QuickQuiz
from .presenters import QuizPresenter
from .serializers import (
    AnswerRequestSerializer,
    AnswerSavedSerializer,
    AttemptHistorySerializer,
    AttemptStartedSerializer,
    AttemptSubmitSerializer,
    CalibrationAnswerSerializer,
    CalibrationSerializer,
    CreateLessonRequestSerializer,
    QuizAttemptSerializer,
    QuizCreatedSerializer,
    QuizCreateSerializer,
    QuizDetailSerializer,
    QuizSubmittedSerializer,
    QuizSummarySerializer,
    TopicTraitsRequestSerializer,
    TopicTraitsSerializer,
)
from .services import CalibrationService, QuickQuizService
from .traits import TopicTraitsService

QUIZZES_TAG = ["quick quizzes"]
QUIZ_ID = OpenApiParameter("quiz_id", str, OpenApiParameter.PATH)
ATTEMPT_ID = OpenApiParameter("attempt_id", str, OpenApiParameter.PATH)


class OwnedQuizzes:
    """Mixin: find the requesting user's quiz, or 404."""

    def quiz_of(self, request, quiz_id: str) -> QuickQuiz:
        try:
            return QuickQuiz.objects.owned_by(request.user).get(pk=parse_id(quiz_id))
        except QuickQuiz.DoesNotExist:
            raise NotFound() from None


class TopicTraitsView(APIView):
    # The composition root for this endpoint; tests swap it for a service with a fake judge.
    traits_factory = staticmethod(TopicTraitsService)

    def get_throttles(self):
        self.throttle_scope = "topic_traits"
        return [ScopedRateThrottle()]

    @extend_schema(
        tags=QUIZZES_TAG,
        summary="Which kinds of question suit a topic",
        description=(
            "A cheap, cached judgement of the topic for the wizard: do numerical questions make sense, may answers be "
            "code. It never fails: when the judge is off or slow the answer is `source: fallback`, and the wizard"
            " offers "
            "every kind the count allows. The server applies the same rule when the quiz is made."
        ),
        request=TopicTraitsRequestSerializer,
        responses={200: TopicTraitsSerializer, 429: OpenApiResponse(description="TOPIC_TRAITS_THROTTLE_RATE.")},
    )
    def post(self, request):
        serializer = TopicTraitsRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        answer = self.traits_factory().of(" ".join(serializer.validated_data["topic"].split()))
        return Response(TopicTraitsSerializer(answer.as_response()).data)


class QuizListCreateView(OwnedQuizzes, generics.ListAPIView):
    pagination_class = LessonCursorPagination
    serializer_class = QuizSummarySerializer
    # The composition root for making a quiz; tests swap it for a service whose topic judge is a fake.
    service_factory = staticmethod(QuickQuizService)

    def get_throttles(self):
        if self.request.method == "POST":
            self.throttle_scope = "quiz_create"
            return [ScopedRateThrottle()]
        return []

    def get_queryset(self):
        return QuickQuiz.objects.owned_by(self.request.user).prefetch_related("attempts")

    @extend_schema(
        tags=QUIZZES_TAG, summary="List your quick quizzes", responses={200: QuizSummarySerializer(many=True)}
    )
    def get(self, request, *args, **kwargs):
        page = self.paginate_queryset(self.get_queryset())
        presenter = QuizPresenter()
        return self.get_paginated_response(QuizSummarySerializer([presenter.summary(q) for q in page], many=True).data)

    @extend_schema(
        tags=QUIZZES_TAG,
        summary="Make a quick quiz",
        description=(
            "From a topic or from up to 10 of your own lessons that have pages. The count is a preset; short and long "
            "answers need 10 or more questions. The level is found by a self-rating, a calibration quiz (a walk of "
            "five questions, `GET /quick-quizzes/{id}/calibration`) or, for lessons, your test scores. Snapshots the "
            "model registry and the flow settings, asks the action gate (`quiz.create`) before anything is created,"
            " and "
            "queues the questions. An optional `Idempotency-Key` header makes a repeated request return the first"
            " answer."
        ),
        parameters=[IDEMPOTENCY_KEY],
        request=QuizCreateSerializer,
        responses={
            202: QuizCreatedSerializer,
            400: OpenApiResponse(
                description="A count that is not a preset, a kind of question the count or topic does not allow, more "
                "than 10 lessons, a count below the number of lessons, a lesson that is only study sheets or not"
                " ready, "
                "or your scores asked for a lesson with no graded test."
            ),
            404: OpenApiResponse(description="A lesson that is not yours."),
            409: OpenApiResponse(description="The same keyed request is still being handled."),
            429: OpenApiResponse(description="QUIZ_CREATE_THROTTLE_RATE."),
            503: OpenApiResponse(description="No model is bound for a step the quiz needs (`llm_not_configured`)."),
        },
    )
    def post(self, request):
        serializer = QuizCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        def start(client_key: str) -> Response:
            created = self.service_factory().create(
                request.user,
                source=dict(data["source"]),
                num_questions=data["num_questions"],
                types=data["types"],
                level=dict(data["level"]),
                idempotency_key=client_key,
            )
            body = QuizCreatedSerializer({"quiz_id": created.quiz.id, "run_id": created.run.id}).data
            return Response(body, status=status.HTTP_202_ACCEPTED)

        return IdempotentRequest().run(request, "quizzes.create", data, start)


class QuizDetailView(OwnedQuizzes, APIView):
    @extend_schema(
        tags=QUIZZES_TAG, summary="Get a quick quiz", parameters=[QUIZ_ID], responses={200: QuizDetailSerializer}
    )
    def get(self, request, quiz_id):
        return Response(QuizDetailSerializer(QuizPresenter().detail(self.quiz_of(request, quiz_id))).data)

    @extend_schema(
        tags=QUIZZES_TAG,
        summary="Delete a quick quiz",
        description=(
            "Stops whatever is running, settles any open authorization as cancelled, erases the quiz's checkpoints, "
            "model calls and calibration, and deletes the quiz with its attempts."
        ),
        parameters=[QUIZ_ID],
        responses={204: None},
    )
    def delete(self, request, quiz_id):
        QuickQuizService().delete(self.quiz_of(request, quiz_id))
        return Response(status=status.HTTP_204_NO_CONTENT)


class CalibrationView(OwnedQuizzes, APIView):
    @extend_schema(
        tags=QUIZZES_TAG,
        summary="The calibration question to answer now",
        description=(
            "One question at a time, with no band, no answer and no hint of what comes next, or `{done: true, level}` "
            "once the five are answered."
        ),
        parameters=[QUIZ_ID],
        responses={
            200: CalibrationSerializer,
            409: OpenApiResponse(description="The quiz is not waiting for calibration."),
        },
    )
    def get(self, request, quiz_id):
        return Response(CalibrationSerializer(CalibrationService().current(self.quiz_of(request, quiz_id))).data)


class CalibrationAnswerView(OwnedQuizzes, APIView):
    @extend_schema(
        tags=QUIZZES_TAG,
        summary="Answer the calibration question",
        description=(
            "Final: the server decides the next question from the ladder. After the last answer the quiz carries on"
            " and the "
            "reply is `{done: true, level}`."
        ),
        parameters=[QUIZ_ID],
        request=CalibrationAnswerSerializer,
        responses={
            200: CalibrationSerializer,
            409: OpenApiResponse(description="`not_current` (another question), `calibration_over` or `wrong_stage`."),
        },
    )
    def post(self, request, quiz_id):
        quiz = self.quiz_of(request, quiz_id)
        serializer = CalibrationAnswerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        body = CalibrationService().answer(quiz, data["question_id"], data["answer"])
        return Response(CalibrationSerializer(body).data)


class QuizAttemptsView(OwnedQuizzes, APIView):
    def get_throttles(self):
        if self.request.method == "POST":
            self.throttle_scope = "quiz_create"
            return [ScopedRateThrottle()]
        return []

    @extend_schema(
        tags=QUIZZES_TAG,
        summary="List the attempts and their trend",
        operation_id="quick_quizzes_attempts_list",
        description="Every attempt, oldest first, and the trend of the graded ones: only this quiz's own are compared.",
        parameters=[QUIZ_ID],
        responses={200: AttemptHistorySerializer},
    )
    def get(self, request, quiz_id):
        body = QuizAttemptService().history(self.quiz_of(request, quiz_id))
        return Response(AttemptHistorySerializer(body).data)

    @extend_schema(
        tags=QUIZZES_TAG,
        summary="Take the quiz again",
        operation_id="quick_quizzes_attempts_start",
        description=(
            "Returns the open attempt if there is one (`200`, so a refresh resumes). Otherwise a retake always"
            " generates a "
            "fresh set, with every question this quiz has asked excluded: `202` with a `run_id`, the attempt waits as "
            "`generating`, and starts when the run ends. Asks the action gate (`quiz.retake`)."
        ),
        parameters=[QUIZ_ID, IDEMPOTENCY_KEY],
        request=None,
        responses={
            200: AttemptStartedSerializer,
            202: AttemptStartedSerializer,
            409: OpenApiResponse(description="The quiz is not ready, or a lesson it was made from was deleted."),
            429: OpenApiResponse(description="QUIZ_CREATE_THROTTLE_RATE."),
        },
    )
    def post(self, request, quiz_id):
        quiz = self.quiz_of(request, quiz_id)

        def start(client_key: str) -> Response:
            taken = QuickQuizService().retake(quiz, client_key)
            attempt = taken.attempt
            ready = attempt.status == attempt.Status.IN_PROGRESS
            shown = QuizAttemptService().shown_questions(attempt)
            body = AttemptStartedSerializer(
                {
                    "attempt_id": attempt.id, "attempt_no": attempt.attempt_no, "status": attempt.status,
                    "run_id": taken.run.id if taken.run else None,
                    "questions": shown, "total_marks": sum(q["marks"] for q in attempt.questions) if ready else 0,
                    "answers": attempt.answers, "started_at": attempt.started_at,
                }
            ).data  # fmt: skip
            return Response(body, status=status.HTTP_200_OK if ready else status.HTTP_202_ACCEPTED)

        return IdempotentRequest().run(request, f"quizzes.retake:{quiz.pk}", {}, start)


class QuizAttemptView(OwnedQuizzes, APIView):
    @extend_schema(
        tags=QUIZZES_TAG,
        summary="Get an attempt",
        operation_id="quick_quizzes_attempt_retrieve",
        description=(
            "While the attempt is in progress: its questions without answer keys and the answers saved so far, so a"
            " refresh "
            "resumes. Once it is over: the same questions, the learner's answers, the score card (with the"
            " per-criterion "
            "marks of written answers) and what to do next (`recommendations`)."
        ),
        parameters=[QUIZ_ID, ATTEMPT_ID],
        responses={200: QuizAttemptSerializer, 404: OpenApiResponse(description="No such attempt.")},
    )
    def get(self, request, quiz_id, attempt_id):
        quiz = self.quiz_of(request, quiz_id)
        attempt = QuizAttemptService().get(quiz, attempt_id)
        return Response(QuizAttemptSerializer(QuizPresenter().attempt(quiz, attempt)).data)


class QuizAttemptAnswerView(OwnedQuizzes, APIView):
    @extend_schema(
        tags=QUIZZES_TAG,
        summary="Save one answer and lock the question",
        description="Forward-only, enforced here: once a question is answered (or left blank) it cannot change.",
        parameters=[QUIZ_ID, ATTEMPT_ID, OpenApiParameter("question_id", str, OpenApiParameter.PATH)],
        request=AnswerRequestSerializer,
        responses={
            200: AnswerSavedSerializer,
            400: OpenApiResponse(description="An unknown question or an answer of the wrong shape."),
            409: OpenApiResponse(description="`locked`, `attempt_sealed` or `wrong_stage` (still preparing)."),
        },
    )
    def put(self, request, quiz_id, attempt_id, question_id):
        serializer = AnswerRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        attempt = QuizAttemptService().save_answer(
            self.quiz_of(request, quiz_id), attempt_id, question_id, serializer.validated_data["answer"]
        )
        body = {"attempt_id": attempt.id, "question_id": question_id, "locked": True, "answered": len(attempt.answers)}
        return Response(AnswerSavedSerializer(body).data)


class QuizAttemptSubmitView(OwnedQuizzes, APIView):
    @extend_schema(
        tags=QUIZZES_TAG,
        summary="Submit an attempt",
        description=(
            "Seals the attempt: missing answers are blank and score 0. Questions with one right answer are marked in"
            " this "
            "request; if there are short or long answers a grading run is queued (`202`, follow `run_id`) and the"
            " attempt "
            "is `grading` until it ends."
        ),
        parameters=[QUIZ_ID, ATTEMPT_ID],
        request=AttemptSubmitSerializer,
        responses={
            200: QuizSubmittedSerializer,
            202: QuizSubmittedSerializer,
            409: OpenApiResponse(description="`attempt_sealed` or `wrong_stage` (still preparing)."),
        },
    )
    def post(self, request, quiz_id, attempt_id):
        serializer = AttemptSubmitSerializer(data=request.data or {})
        serializer.is_valid(raise_exception=True)
        attempt, run = QuizAttemptService().submit(
            self.quiz_of(request, quiz_id), attempt_id, serializer.validated_data.get("answers")
        )
        body = QuizSubmittedSerializer(
            {
                "attempt_id": attempt.id, "attempt_no": attempt.attempt_no, "run_id": run.id if run else None,
                "status": attempt.status, "awarded": attempt.awarded, "available": attempt.available,
                "band": attempt.band, "result": attempt.result,
            }
        ).data  # fmt: skip
        return Response(body, status=status.HTTP_202_ACCEPTED if run else status.HTTP_200_OK)


class QuizAttemptRegradeView(OwnedQuizzes, APIView):
    @extend_schema(
        tags=QUIZZES_TAG,
        summary="Grade a failed attempt again",
        parameters=[QUIZ_ID, ATTEMPT_ID],
        request=None,
        responses={
            202: QuizCreatedSerializer,
            409: OpenApiResponse(description="Only an attempt whose grading failed, with no run going."),
        },
    )
    def post(self, request, quiz_id, attempt_id):
        quiz = self.quiz_of(request, quiz_id)
        run = QuizAttemptService().regrade(quiz, attempt_id)
        return Response(
            QuizCreatedSerializer({"quiz_id": quiz.id, "run_id": run.id}).data, status=status.HTTP_202_ACCEPTED
        )


class QuizCreateLessonView(OwnedQuizzes, APIView):
    def get_throttles(self):
        self.throttle_scope = "lesson_create"  # it makes a lesson
        return [ScopedRateThrottle()]

    @extend_schema(
        tags=QUIZZES_TAG,
        summary="Create a lesson for this",
        description=(
            "For a quiz about a topic: a lesson on that topic whose level is found from the result (the quiz's level"
            " moved "
            "by how the attempt went), with the concepts it showed as gaps. The same as `POST /lessons` with "
            "`entry: quiz_result`. A quiz made from lessons is refused: study those lessons instead."
        ),
        parameters=[QUIZ_ID, IDEMPOTENCY_KEY],
        request=CreateLessonRequestSerializer,
        responses={
            202: LessonCreatedSerializer,
            400: OpenApiResponse(description="`not_a_topic_quiz`."),
            404: OpenApiResponse(description="No graded attempt of yours with that id."),
        },
    )
    def post(self, request, quiz_id):
        quiz = self.quiz_of(request, quiz_id)
        serializer = CreateLessonRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def start(client_key: str) -> Response:
            lesson, run = QuickQuizService().create_lesson(quiz, serializer.validated_data["attempt_id"], client_key)
            body = LessonCreatedSerializer({"lesson_id": lesson.id, "run_id": run.id}).data
            return Response(body, status=status.HTTP_202_ACCEPTED)

        return IdempotentRequest().run(request, f"quizzes.create_lesson:{quiz.pk}", serializer.validated_data, start)
