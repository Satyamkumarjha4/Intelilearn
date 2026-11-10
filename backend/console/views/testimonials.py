from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.response import Response

from console.serializers_testimonials import (
    ReorderInputSerializer,
    TestimonialInputSerializer,
    TestimonialListSerializer,
    TestimonialSerializer,
)
from console.services.testimonials import TestimonialDesk

from .base import CONSOLE_TAG, ConsoleView


class TestimonialListView(ConsoleView):
    @extend_schema(
        tags=CONSOLE_TAG,
        summary="The landing page's testimonials",
        description="Every testimonial, published or not, samples included, in the order the landing page shows them.",
        responses={200: TestimonialListSerializer},
    )
    def get(self, request):
        return Response({"testimonials": TestimonialSerializer(TestimonialDesk(self.audit).listing(), many=True).data})

    @extend_schema(
        tags=CONSOLE_TAG,
        summary="Add a testimonial",
        description=(
            "Goes last, never a sample. Publishing needs the learner's consent confirmed (`consent_confirmed`); "
            "otherwise it is refused with the reason. Written to the change log."
        ),
        request=TestimonialInputSerializer,
        responses={201: TestimonialSerializer, 400: OpenApiResponse(description="A field is not valid.")},
    )
    def post(self, request):
        data = TestimonialInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        row = TestimonialDesk(self.audit).create(data.validated_data)
        return Response(TestimonialSerializer(row).data, status=status.HTTP_201_CREATED)


class TestimonialDetailView(ConsoleView):
    @extend_schema(
        tags=CONSOLE_TAG,
        summary="Edit, publish or unpublish a testimonial",
        description=(
            "Any subset of the fields; publishing is `is_published`. Refused with the reason when publishing without "
            "consent, when the testimonial is a sample, or when consent is taken away while it is published. Nothing "
            "is written when nothing changes."
        ),
        request=TestimonialInputSerializer,
        responses={200: TestimonialSerializer, 400: OpenApiResponse(description="A field is not valid.")},
    )
    def patch(self, request, testimonial_id):
        data = TestimonialInputSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        return Response(
            TestimonialSerializer(TestimonialDesk(self.audit).update(testimonial_id, data.validated_data)).data
        )

    @extend_schema(
        tags=CONSOLE_TAG,
        summary="Delete a testimonial",
        description="Removes it for good; the change log keeps what it said.",
        responses={204: None},
    )
    def delete(self, request, testimonial_id):
        TestimonialDesk(self.audit).delete(testimonial_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class TestimonialReorderView(ConsoleView):
    @extend_schema(
        tags=CONSOLE_TAG,
        summary="Reorder the testimonials",
        description="`ids` must name every testimonial exactly once; positions are renumbered from 1 in this order.",
        request=ReorderInputSerializer,
        responses={200: TestimonialListSerializer, 400: OpenApiResponse(description="`ids` is not every id once.")},
    )
    def post(self, request):
        data = ReorderInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        rows = TestimonialDesk(self.audit).reorder(data.validated_data["ids"])
        return Response({"testimonials": TestimonialSerializer(rows, many=True).data})
