from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .domain import SuggestionRequest
from .serializers import TopicSuggestionsRequestSerializer, TopicSuggestionsSerializer
from .service import TopicSuggester


class TopicSuggestionsView(APIView):
    # The composition root for this endpoint; tests swap it for a suggester with a fake model.
    suggester_factory = staticmethod(TopicSuggester.default)

    def get_throttles(self):
        # Per learner: a request can cost a model call.
        self.throttle_scope = "topic_suggestions"
        return [ScopedRateThrottle()]

    @extend_schema(
        tags=["onboarding"],
        summary="Suggest four first topics",
        description=(
            "Four topics for the learner to start with, from their education level, class or year, field of study, "
            "goal and language: before the profile is saved. They come from a curated catalogue, instantly; a model "
            "is asked only for a field of study the catalogue does not know, and to translate. Whatever goes wrong "
            "with a model, the answer is still `200` with English catalogue topics (`source: fallback`). `page` pages "
            "through the list four at a time and wraps; `has_more` says whether there are others."
        ),
        request=TopicSuggestionsRequestSerializer,
        responses={
            200: TopicSuggestionsSerializer,
            400: OpenApiResponse(description="A choice outside the profile's, or a text or page that is out of range."),
            429: OpenApiResponse(description="30 requests a minute per learner."),
        },
    )
    def post(self, request):
        serializer = TopicSuggestionsRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        suggestions = self.suggester_factory().suggest(SuggestionRequest(**serializer.validated_data))
        return Response(TopicSuggestionsSerializer(suggestions.as_dict()).data)
