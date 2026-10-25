from drf_spectacular.utils import extend_schema
from rest_framework.response import Response

from console.serializers import OverviewSerializer, RangeQuerySerializer
from console.services.overview import OverviewReport

from .base import CONSOLE_TAG, ConsoleView


class OverviewView(ConsoleView):
    #: the health card's checks; a class attribute so a test can swap in a fake instead of reaching Redis and Celery
    health = None

    @extend_schema(
        tags=CONSOLE_TAG,
        summary="The overview",
        description=(
            "How Socra is doing over a range: health, lessons, spend, calls, a daily spend chart, where lessons stop, "
            "the slowest steps and what needs attention. The range starts at midnight (UTC) and ends now. A call is "
            "an *attempt*: `ok` worked first time, `retried` worked on a later attempt, `failed` did not work, so the "
            "three add up to `total`; `fallbacks` counts attempts on a later model of a step's chain, of any result."
        ),
        parameters=[RangeQuerySerializer],
        responses={200: OverviewSerializer},
    )
    def get(self, request):
        query = RangeQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        report = OverviewReport(health=self.health).build(query.validated_data["range"])
        return Response(OverviewSerializer(report).data)
