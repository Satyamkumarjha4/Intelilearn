from drf_spectacular.utils import OpenApiParameter, extend_schema

from console.models import AuditEntry
from console.pagination import ConsoleCursorPagination
from console.serializers import AuditEntrySerializer, LearnerPageSerializer, LearnerSerializer
from console.services.learners import LearnerQuery, LearnerSummary, VerificationFilters

from .base import CONSOLE_TAG, ConsoleListView


class LearnerListView(ConsoleListView):
    serializer_class = LearnerSerializer

    class Pagination(ConsoleCursorPagination):
        ordering = "-date_joined"

    pagination_class = Pagination

    def get_queryset(self):
        params = self.request.query_params
        return LearnerQuery().queryset(params.get("q", ""), params.get("verification", ""))

    def get_paginated_response(self, data):
        response = super().get_paginated_response(data)
        response.data["summary"] = LearnerSummary().of_everyone()
        return response

    @extend_schema(
        tags=CONSOLE_TAG,
        summary="List learners",
        description=(
            "Everyone with an account, newest first: their profile choices, lesson count, last activity and whether "
            "their profile is complete, and whether their email is verified, who vouched for it and whether it is "
            "locked. Read-only, and without anything they wrote about themselves. `summary` counts every learner, "
            "whatever the search or the filter, including how many are `unverified`, `legacy` or `locked`."
        ),
        parameters=[
            OpenApiParameter("q", str, description="Search the name or email."),
            OpenApiParameter(
                "verification",
                str,
                enum=VerificationFilters.names(),
                description=(
                    "Keep one sign-in state (open accounts only): `unverified` (the email was never proved), `legacy` "
                    "(from before verification, never proved) or `locked` (too many dead codes lately). Another value "
                    "is a `400` naming `verification`."
                ),
            ),
        ],
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
