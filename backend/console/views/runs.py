from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from console.pagination import ConsoleCursorPagination
from console.serializers import (
    RunCancelledSerializer,
    RunDetailSerializer,
    RunQuerySerializer,
    RunRetriedSerializer,
    RunRowSerializer,
)
from console.services.runs import RunActions, RunDetail, RunQuery

from .base import CONSOLE_TAG, ConsoleListView, ConsoleView

RUN_ID = OpenApiParameter("run_id", str, OpenApiParameter.PATH)


class RunListView(ConsoleListView):
    serializer_class = RunRowSerializer

    class Pagination(ConsoleCursorPagination):
        ordering = "-created_at"

    pagination_class = Pagination

    def get_queryset(self):
        query = RunQuerySerializer(data=self.request.query_params)
        query.is_valid(raise_exception=True)
        data = query.validated_data
        return RunQuery().queryset(
            statuses=data.get("status", []), graphs=data.get("graph", []), search=data.get("q", "")
        )

    @extend_schema(
        tags=CONSOLE_TAG,
        summary="List runs",
        description=(
            "Every execution of a lesson graph (a lesson build, a quiz resume, a repair, a grading job), newest first, "
            "for any learner. `calls` and `cost` are the model calls the run made."
        ),
        parameters=[RunQuerySerializer],
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class RunLookup:
    def run_of(self, run_id: str):
        run = RunQuery().get(run_id)
        if run is None:
            raise NotFound()
        return run


class RunDetailView(RunLookup, ConsoleView):
    @extend_schema(
        tags=CONSOLE_TAG,
        summary="One run",
        description=(
            "The run with its error, a timeline of its steps and its last 20 model calls. The timeline comes from the "
            "start and finish times the run keeps for each graph node, measured from when the run started. A step is "
            "`failed` if it failed (or was skipped after failing), `waiting` if it is where a paused run waits for the "
            "learner (no duration), `retried` if the graph ran it again after its output failed a check, otherwise "
            "`ran`; a step still running shows its time so far. Runs from before times were kept list their steps "
            "without times. Model-level retries and fallbacks are in `model_calls` (`attempt`, `fallback_index`)."
        ),
        parameters=[RUN_ID],
        responses={200: RunDetailSerializer, 404: OpenApiResponse(description="No such run.")},
    )
    def get(self, request, run_id):
        return Response(RunDetailSerializer(RunDetail().of(self.run_of(run_id))).data)


class RunRetryView(RunLookup, ConsoleView):
    @extend_schema(
        tags=CONSOLE_TAG,
        summary="Retry a failed lesson",
        description=(
            "The learner's Retry, as staff: resumes the lesson from its last checkpoint with a new run. Only a "
            "lesson build can be retried here."
        ),
        parameters=[RUN_ID],
        request=None,
        responses={
            202: RunRetriedSerializer,
            409: OpenApiResponse(description="`wrong_stage`, `run_in_progress` or `not_retryable`."),
        },
    )
    def post(self, request, run_id):
        run = self.run_of(run_id)
        new = RunActions(self.audit).retry(run)
        return Response(RunRetriedSerializer({"run_id": new.id, "lesson_id": run.lesson_id}).data, status=202)


class RunCancelView(RunLookup, ConsoleView):
    @extend_schema(
        tags=CONSOLE_TAG,
        summary="Cancel a run",
        description="Stops the run after its current step. The lesson is marked failed, so it can be retried.",
        parameters=[RUN_ID],
        request=None,
        responses={202: RunCancelledSerializer, 409: OpenApiResponse(description="`run_ended`.")},
    )
    def post(self, request, run_id):
        run = RunActions(self.audit).cancel(self.run_of(run_id))
        return Response(RunCancelledSerializer({"id": run.id, "status": run.status}).data, status=202)
