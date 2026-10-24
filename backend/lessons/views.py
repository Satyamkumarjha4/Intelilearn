"""Thin views for the lessons API: parse, call a service, format. Every query starts from the requesting user's own
lessons (`Lesson.objects.owned_by`), so another user's lesson or run is a 404, never a 403."""

import uuid

from django.conf import settings
from django.http import StreamingHttpResponse
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import NotFound
from rest_framework.pagination import CursorPagination
from rest_framework.renderers import BaseRenderer, JSONRenderer
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .events import RunEventStream, RunSnapshot
from .models import GraphRun, Lesson, MaterialKind, Stage
from .serializers import (
    LessonCreatedSerializer,
    LessonCreateSerializer,
    LessonDetailSerializer,
    LessonSummarySerializer,
    MaterialKindSerializer,
    PracticeGradeRequestSerializer,
    PracticeGradeSerializer,
    QuizAttemptRequestSerializer,
    QuizAttemptResponseSerializer,
    QuizForLearnerSerializer,
    QuizReviewSerializer,
    RunSerializer,
    RunStartedSerializer,
    StudyMaterialSerializer,
)
from .services import LessonService, MaterialService, QuizService

LESSONS_TAG = ["lessons"]
QUIZZES_TAG = ["quizzes"]
MATERIALS_TAG = ["study sheets"]
RUNS_TAG = ["runs"]
LESSON_ID = OpenApiParameter("lesson_id", str, OpenApiParameter.PATH)
KIND = OpenApiParameter("kind", str, OpenApiParameter.PATH, enum=["diagnostic", "prerequisite"])


def parse_id(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise NotFound() from None


class OwnedLessons:
    """Mixin: find the requesting user's lesson, or 404."""

    def lesson_of(self, request, lesson_id: str) -> Lesson:
        try:
            return Lesson.objects.owned_by(request.user).get(pk=parse_id(lesson_id))
        except Lesson.DoesNotExist:
            raise NotFound() from None


class LessonCursorPagination(CursorPagination):
    ordering = "-created_at"
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class LessonListCreateView(generics.ListAPIView):
    pagination_class = LessonCursorPagination
    serializer_class = LessonSummarySerializer

    def get_throttles(self):
        if self.request.method == "POST":
            self.throttle_scope = "lesson_create"
            return [ScopedRateThrottle()]
        return []

    def get_queryset(self):
        lessons = Lesson.objects.owned_by(self.request.user)
        if query := self.request.query_params.get("q", "").strip():
            lessons = lessons.filter(topic__icontains=query)
        if stage := self.request.query_params.get("stage"):
            lessons = lessons.filter(stage=stage)
        return lessons

    @extend_schema(
        tags=LESSONS_TAG,
        summary="List your lessons",
        parameters=[
            OpenApiParameter("q", str, description="Search the topic."),
            OpenApiParameter("stage", str, enum=[value for value, _ in Stage.choices]),
        ],
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(
        tags=LESSONS_TAG,
        summary="Start a lesson",
        description="Snapshots the model registry and the flow settings, and queues the diagnostic.",
        request=LessonCreateSerializer,
        responses={
            202: LessonCreatedSerializer,
            503: OpenApiResponse(description="No model is bound for the first step (`llm_not_configured`)."),
        },
    )
    def post(self, request):
        serializer = LessonCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        lesson, run = LessonService().create(request.user, **serializer.validated_data)
        body = LessonCreatedSerializer({"lesson_id": lesson.id, "run_id": run.id}).data
        return Response(body, status=status.HTTP_202_ACCEPTED)


class LessonDetailView(OwnedLessons, APIView):
    @extend_schema(tags=LESSONS_TAG, summary="Get a lesson", parameters=[LESSON_ID],
                   responses={200: LessonDetailSerializer})  # fmt: skip
    def get(self, request, lesson_id):
        return Response(LessonDetailSerializer(self.lesson_of(request, lesson_id)).data)

    @extend_schema(
        tags=LESSONS_TAG,
        summary="Delete a lesson",
        description="Cancels any active run and deletes the lesson with its quizzes and media.",
        parameters=[LESSON_ID],
        responses={204: None},
    )
    def delete(self, request, lesson_id):
        LessonService().delete(self.lesson_of(request, lesson_id))
        return Response(status=status.HTTP_204_NO_CONTENT)


class LessonRetryView(OwnedLessons, APIView):
    @extend_schema(
        tags=LESSONS_TAG,
        summary="Retry a failed lesson",
        description="Resumes the lesson's graph from its last checkpoint. Only when `stage` is `failed`.",
        parameters=[LESSON_ID],
        request=None,
        responses={202: RunStartedSerializer, 409: OpenApiResponse(description="Not failed, or a run is active.")},
    )
    def post(self, request, lesson_id):
        run = LessonService().retry(self.lesson_of(request, lesson_id))
        return Response({"run_id": run.id}, status=status.HTTP_202_ACCEPTED)


class QuizView(OwnedLessons, APIView):
    @extend_schema(
        tags=QUIZZES_TAG,
        summary="Get a quiz to answer",
        description="Questions without answers, explanations or concepts.",
        parameters=[LESSON_ID, KIND],
        responses={200: QuizForLearnerSerializer},
    )
    def get(self, request, lesson_id, kind):
        return Response(QuizService().for_learner(self.lesson_of(request, lesson_id), kind))


class QuizAttemptView(OwnedLessons, APIView):
    @extend_schema(
        tags=QUIZZES_TAG,
        summary="Answer a quiz",
        description=(
            "Graded at once; the lesson's graph then resumes. `400` if any question is unanswered, `409` if the quiz "
            "was already answered or the lesson is not waiting for it."
        ),
        parameters=[LESSON_ID, KIND],
        request=QuizAttemptRequestSerializer,
        responses={202: QuizAttemptResponseSerializer},
    )
    def post(self, request, lesson_id, kind):
        serializer = QuizAttemptRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        summary, run = QuizService().submit(
            self.lesson_of(request, lesson_id), kind, serializer.validated_data["answers"]
        )
        return Response({"result": summary, "run_id": run.id}, status=status.HTTP_202_ACCEPTED)


class QuizReviewView(OwnedLessons, APIView):
    @extend_schema(
        tags=QUIZZES_TAG,
        summary="Review an answered quiz",
        description="The learner's answers next to the correct ones, with explanations. Only after the attempt.",
        parameters=[LESSON_ID, KIND],
        responses={200: QuizReviewSerializer},
    )
    def get(self, request, lesson_id, kind):
        return Response(QuizService().review(self.lesson_of(request, lesson_id), kind))


class MaterialChoiceView(OwnedLessons, APIView):
    @extend_schema(
        tags=MATERIALS_TAG,
        summary="Choose the first study sheet",
        description="After a perfect diagnostic. Resumes the lesson's flow. Only when `stage` is `awaiting_choice`.",
        parameters=[LESSON_ID],
        request=MaterialKindSerializer,
        responses={202: RunStartedSerializer, 409: OpenApiResponse(description="Not waiting for the choice.")},
    )
    def post(self, request, lesson_id):
        serializer = MaterialKindSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        run = MaterialService().choose(self.lesson_of(request, lesson_id), serializer.validated_data["kind"])
        return Response({"run_id": run.id}, status=status.HTTP_202_ACCEPTED)


class MaterialRequestView(OwnedLessons, APIView):
    @extend_schema(
        tags=MATERIALS_TAG,
        summary="Ask for another study sheet",
        description="For a ready mastery lesson. Runs the small `study_material` graph; the lesson stays `ready`.",
        parameters=[LESSON_ID],
        request=MaterialKindSerializer,
        responses={
            202: RunStartedSerializer,
            409: OpenApiResponse(description="Wrong stage, exists, or a run is active."),
        },
    )
    def post(self, request, lesson_id):
        serializer = MaterialKindSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        run = MaterialService().request_extra(self.lesson_of(request, lesson_id), serializer.validated_data["kind"])
        return Response({"run_id": run.id}, status=status.HTTP_202_ACCEPTED)


class MaterialView(OwnedLessons, APIView):
    @extend_schema(
        tags=MATERIALS_TAG,
        summary="Get a study sheet",
        description=(
            "A practice sheet comes without solutions. `reveal=<question id>` (repeat it, or comma-separate) or "
            "`reveal=all` adds them under `solutions`."
        ),
        parameters=[
            LESSON_ID,
            OpenApiParameter("kind", str, OpenApiParameter.PATH, enum=[value for value, _ in MaterialKind.choices]),
            OpenApiParameter(
                "reveal", str, many=True, description="Question ids whose solutions to include, or `all`."
            ),
        ],
        responses={200: StudyMaterialSerializer},
    )
    def get(self, request, lesson_id, kind):
        reveal = [part for value in request.query_params.getlist("reveal") for part in value.split(",") if part]
        return Response(MaterialService().get(self.lesson_of(request, lesson_id), kind, reveal))


class PracticeGradeView(OwnedLessons, APIView):
    @extend_schema(
        tags=MATERIALS_TAG,
        summary="Grade a practice sheet",
        description=(
            "Multiple-choice and numerical answers are marked. Short, long and code answers are not, and show their "
            "solution for self-checking. Nothing is stored: practice can be repeated."
        ),
        parameters=[LESSON_ID],
        request=PracticeGradeRequestSerializer,
        responses={200: PracticeGradeSerializer},
    )
    def post(self, request, lesson_id):
        serializer = PracticeGradeRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(
            MaterialService().grade_practice(self.lesson_of(request, lesson_id), serializer.validated_data["answers"])
        )


class OwnedRuns:
    def run_of(self, request, run_id: str) -> GraphRun:
        try:
            return GraphRun.objects.select_related("lesson").get(pk=parse_id(run_id), lesson__owner=request.user)
        except GraphRun.DoesNotExist:
            raise NotFound() from None


RUN_ID = OpenApiParameter("run_id", str, OpenApiParameter.PATH)


class RunView(OwnedRuns, APIView):
    @extend_schema(tags=RUNS_TAG, summary="Get a run", parameters=[RUN_ID], responses={200: RunSerializer})
    def get(self, request, run_id):
        return Response(RunSerializer(self.run_of(request, run_id)).data)


class EventStreamRenderer(BaseRenderer):
    """Lets a browser's EventSource (`Accept: text/event-stream`) through content negotiation. The view writes the
    stream itself; an error is switched back to JSON by `RunEventsView.handle_exception`."""

    media_type = "text/event-stream"
    format = "event-stream"
    charset = "utf-8"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        return b""


class RunEventsView(OwnedRuns, APIView):
    renderer_classes = [EventStreamRenderer, JSONRenderer]

    def handle_exception(self, exc):
        response = super().handle_exception(exc)
        self.request.accepted_renderer = JSONRenderer()
        self.request.accepted_media_type = "application/json"
        return response

    @extend_schema(
        tags=RUNS_TAG,
        summary="Follow a run (Server-Sent Events)",
        description=(
            "`snapshot` first, then `node`, `model` and `warning` events, ending with one of `awaiting_input`, "
            "`done`, `error` or `cancelled`. `: ping` comments keep the connection alive."
        ),
        parameters=[RUN_ID],
        responses={(200, "text/event-stream"): OpenApiResponse(description="An event stream.")},
    )
    def get(self, request, run_id):
        run = self.run_of(request, run_id)
        stream = RunEventStream(heartbeat_s=settings.SSE_HEARTBEAT_S).events(run.id, RunSnapshot(run.id))
        response = StreamingHttpResponse(stream, content_type="text/event-stream")
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response


class RunCancelView(OwnedRuns, APIView):
    @extend_schema(
        tags=RUNS_TAG,
        summary="Cancel a run",
        description="Stops the run after its current step. The lesson is marked failed, so it can be retried.",
        parameters=[RUN_ID],
        request=None,
        responses={202: None, 409: OpenApiResponse(description="The run already ended.")},
    )
    def post(self, request, run_id):
        run = self.run_of(request, run_id)
        LessonService().cancel(run)
        return Response(status=status.HTTP_202_ACCEPTED)
