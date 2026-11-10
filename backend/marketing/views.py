from django.utils.cache import patch_cache_control
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from credits.pricing.public import PublicPricing

from .serializers import (
    PublicPricingSerializer,
    PublicTestimonialsSerializer,
)
from .testimonials import PublicTestimonials


class PublicView(APIView):
    """What the landing page reads for visitors without an account: open, limited per client address, and kept by a
    browser or a proxy for a short while (the server caches it as well, and clears that cache on every change)."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "public_pages"
    BROWSER_CACHE_S = 30

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        if response.status_code == 200:
            patch_cache_control(response, public=True, max_age=self.BROWSER_CACHE_S)
        return response


class PublicTestimonialsView(PublicView):
    @extend_schema(
        tags=["landing"],
        summary="The testimonials shown on the landing page",
        description=(
            "Only testimonials that are published, whose learner confirmed consent, and that are not samples, in the "
            "order the console puts them. A sample is never returned, whatever the server's DEBUG setting. Empty when "
            "there are none, and the page then shows the maker's note instead."
        ),
        responses={
            200: PublicTestimonialsSerializer,
            429: OpenApiResponse(description="Too many requests from this address (60 a minute)."),
        },
    )
    def get(self, request):
        return Response({"testimonials": PublicTestimonials().listing()})


class PublicPricingView(PublicView):
    @extend_schema(
        tags=["landing"],
        summary="Plans, prices and what credits buy, for the landing page",
        description=(
            "Read from the same rows and rules the checkout and the credit gate use, so it always equals what is "
            "charged. Money is in paise. `about_lessons` is whole full lessons, rounded down. A price with no live "
            "row is null, never free."
        ),
        responses={
            200: PublicPricingSerializer,
            429: OpenApiResponse(description="Too many requests from this address (60 a minute)."),
        },
    )
    def get(self, request):
        return Response(PublicPricing().payload())
