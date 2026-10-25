from drf_spectacular.utils import OpenApiParameter, extend_schema

from console.models import AuditEntry
from console.pagination import ConsoleCursorPagination
from console.serializers import AuditEntrySerializer, LearnerPageSerializer, LearnerSerializer
from console.services.learners import LearnerQuery, LearnerSummary

from .base import CONSOLE_TAG, ConsoleListView


class LearnerListView(ConsoleListView):
    serializer_class = LearnerSerializer

    class Pagination(ConsoleCursorPagination):
        ordering = "-date_joined"

    pagination_class = Pagination

    def get_queryset(self):
        return LearnerQuery().queryset(self.request.query_params.get("q", ""))

    def get_paginated_response(self, data):
        response = super().get_paginated_response(data)
        response.data["summary"] = LearnerSummary().of_everyone()
        return response

    @extend_schema(
        tags=CONSOLE_TAG,
        summary="List learners",
        description=(
            "Everyone with an account, newest first: their profile choices, lesson count, last activity and whether "
            "their profile is complete. Read-only, and without anything they wrote about themselves. `summary` counts "
            "every learner, whatever the search."
        ),
        parameters=[OpenApiParameter("q", str, description="Search the name or email.")],
        responses={200: LearnerPageSerializer},
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class AuditListView(ConsoleListView):
    serializer_class = AuditEntrySerializer

    class Pagination(ConsoleCursorPagination):
        ordering = "-id"  # the order they were written in, and unlike a timestamp it never ties

    pagination_class = Pagination

    def get_queryset(self):
        return AuditEntry.objects.select_related("actor")

    @extend_schema(
        tags=CONSOLE_TAG,
        summary="The change log",
        description=(
            "Every change made through the console, newest first: who, what, the target, and its state before and "
            "after. Entries are never edited or deleted. Page with `cursor`."
        ),
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)
