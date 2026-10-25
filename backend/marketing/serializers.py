from rest_framework import serializers

from .models import DemoQuestion


class OutcomeSerializer(serializers.Serializer):
    level = serializers.IntegerField(min_value=1, max_value=5, help_text="How many of the five level segments are lit.")
    level_label = serializers.CharField()
    lesson_start = serializers.CharField(help_text="Where the lesson would begin, in a sentence.")


class DemoQuestionSerializer(serializers.ModelSerializer):
    options = serializers.ListField(child=serializers.CharField(), min_length=3, max_length=3)
    outcome_right = OutcomeSerializer()
    outcome_wrong = OutcomeSerializer(help_text='For a wrong answer or "I don\'t know".')

    class Meta:
        model = DemoQuestion
        fields = [
            "id",
            "subject",
            "level_label",
            "band",
            "question",
            "options",
            "correct_index",
            "outcome_right",
            "outcome_wrong",
        ]
        read_only_fields = fields


class DemoQuestionQuerySerializer(serializers.Serializer):
    exclude = serializers.IntegerField(required=False, min_value=0, help_text="A question id not to return.")
