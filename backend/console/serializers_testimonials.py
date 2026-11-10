"""The shapes of the console's testimonial endpoints (docs/reference/api.md, "Console")."""

from rest_framework import serializers

from marketing.models import Testimonial


class TestimonialSerializer(serializers.ModelSerializer):
    class Meta:
        model = Testimonial
        fields = [
            "id", "name", "context", "quote", "rating", "position", "is_published", "consent_confirmed", "is_sample",
            "created_at", "updated_at",
        ]  # fmt: skip
        read_only_fields = fields


class TestimonialListSerializer(serializers.Serializer):
    testimonials = TestimonialSerializer(many=True)


class TestimonialInputSerializer(serializers.ModelSerializer):
    """What the console may send. The sample flag and the position are not here: a sample cannot be made or promoted
    from the console, and the order is changed only by reordering."""

    rating = serializers.IntegerField(min_value=1, max_value=5, allow_null=True, required=False)

    class Meta:
        model = Testimonial
        fields = ["name", "context", "quote", "rating", "is_published", "consent_confirmed"]


class ReorderInputSerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.IntegerField(), help_text="Every testimonial's id, in the new order.")
