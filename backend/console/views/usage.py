from django.http import StreamingHttpResponse
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.response import Response

from console.periods import Periods
from console.serializers import UsageQuerySerializer, UsageSerializer
from console.services.usage import UsageCsv, UsageFilters, UsageReport

from .base import CONSOLE_TAG, ConsoleView


class UsageFiltersMixin:
    def filters(self, request) -> UsageFilters:
        query = UsageQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        data = dict(query.validated_data)
        key = data.pop("range")
        if key == "custom":
            period = Periods().custom(data.pop("start"), data.pop("end"))
        else:
            period = Periods().of(key)
        return UsageFilters.of(period, **data)


class UsageView(UsageFiltersMixin, ConsoleView):
    @extend_schema(
        tags=CONSOLE_TAG,
        summary="Usage and cost",
        description=(
            "Every model call in the range, totalled overall, per model and per step. Call times are of the calls "
            "that worked, as interpolated percentiles. A call is an *attempt*: `retried` is an attempt that worked "
            "after at least one earlier attempt on the same model (attempt > 1); `failed` is any status but ok; a "
            "fallback is an attempt on the step's second or later model (fallback_index > 0)."
        ),
        parameters=[UsageQuerySerializer],
        responses={200: UsageSerializer},
    )
    def get(self, request):
        return Response(UsageSerializer(UsageReport().build(self.filters(request))).data)


class UsageExportView(UsageFiltersMixin, ConsoleView):
    @extend_schema(
        tags=CONSOLE_TAG,
        summary="Export the calls as CSV",
        description=(
            "The calls the same filters select as `usage`, one row each, oldest first, streamed. `outcome` is named "
            "like the usage page names it. Text that a spreadsheet would run as a formula starts with an apostrophe."
        ),
        parameters=[UsageQuerySerializer],
        responses={(200, "text/csv"): OpenApiResponse(description="A CSV file.")},
    )
    def get(self, request):
        filters, csv_file = self.filters(request), UsageCsv()
        response = StreamingHttpResponse(csv_file.rows(filters), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{csv_file.filename(filters)}"'
        return response
