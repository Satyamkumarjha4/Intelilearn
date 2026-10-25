from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .picker import DemoQuestionPicker
from .serializers import DemoQuestionQuerySerializer, DemoQuestionSerializer


class DemoQuestionView(APIView):
    """The landing page's try-it question. Public: visitors have no account."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "landing_demo"  # per client address
    picker_factory = staticmethod(DemoQuestionPicker)

    @extend_schema(
        tags=["landing"],
        summary="A random question for the landing page's try-it card",
        description=(
            "One random active question, with the outcome of a right and of a wrong answer. `exclude` is the id of a "
            "question not to return (the one just shown), unless it is the only one. Never cached, so every call "
            "can differ. `404` when no question is active."
        ),
        parameters=[DemoQuestionQuerySerializer],
        responses={
            200: DemoQuestionSerializer,
            400: OpenApiResponse(description="`exclude` is not a whole number."),
            404: OpenApiResponse(description="No question is active."),
            429: OpenApiResponse(description="Too many requests from this address (60 a minute)."),
        },
    )
    @method_decorator(never_cache)
    def get(self, request):
        query = DemoQuestionQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        question = self.picker_factory().pick(query.validated_data.get("exclude"))
        if question is None:
            raise NotFound("There is no question to show.")
        return Response(DemoQuestionSerializer(question).data)
