"""Request and response shapes of the lessons API (docs/api.md). Responses are built from the services' output."""

from rest_framework import serializers

from .models import GraphRun, Lesson, Quiz, QuizAttempt
from .stages import MaterialKind, Route


class LessonCreateSerializer(serializers.Serializer):
    topic = serializers.CharField(min_length=2, max_length=200)
    user_context = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")


class LessonCreatedSerializer(serializers.Serializer):
    lesson_id = serializers.UUIDField()
    run_id = serializers.UUIDField()


class RunStartedSerializer(serializers.Serializer):
    run_id = serializers.UUIDField()


class LessonSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Lesson
        fields = ["id", "topic", "stage", "route", "title", "level", "created_at", "updated_at"]
        read_only_fields = fields


class QuizResultSummarySerializer(serializers.Serializer):
    correct = serializers.IntegerField()
    total = serializers.IntegerField()
    dont_know = serializers.IntegerField()
    by_band = serializers.DictField(child=serializers.ListField(child=serializers.IntegerField()))
    route = serializers.ChoiceField(choices=Route.choices, required=False)


class AssessmentSerializer(serializers.Serializer):
    """What the learner may see of the assessment (not the notes for the page writers)."""

    level = serializers.CharField()
    known_concepts = serializers.ListField(child=serializers.CharField())
    gaps = serializers.ListField(child=serializers.CharField())
    start_point = serializers.CharField()
    confidence = serializers.CharField()


class LessonDetailSerializer(LessonSummarySerializer):
    user_context = serializers.CharField()
    error = serializers.CharField()
    warnings = serializers.ListField(child=serializers.CharField())
    assessment = serializers.SerializerMethodField()
    prerequisites_to_cover = serializers.SerializerMethodField()
    active_run_id = serializers.SerializerMethodField()
    results = serializers.SerializerMethodField()
    materials = serializers.SerializerMethodField()

    class Meta(LessonSummarySerializer.Meta):
        fields = [
            *LessonSummarySerializer.Meta.fields,
            "user_context",
            "error",
            "warnings",
            "assessment",
            "prerequisites_to_cover",
            "active_run_id",
            "results",
            "materials",
        ]
        read_only_fields = fields

    def get_assessment(self, lesson: Lesson) -> dict | None:
        if not lesson.assessment:
            return None
        return AssessmentSerializer(lesson.assessment).data

    def get_prerequisites_to_cover(self, lesson: Lesson) -> list[str]:
        return [p["name"] for p in lesson.prerequisites_to_cover]

    def get_active_run_id(self, lesson: Lesson) -> str | None:
        run = lesson.runs.filter(status__in=[GraphRun.Status.QUEUED, GraphRun.Status.RUNNING]).first()
        return str(run.id) if run else None

    def get_materials(self, lesson: Lesson) -> list[str]:
        return sorted(lesson.materials.values_list("kind", flat=True))

    def get_results(self, lesson: Lesson) -> dict:
        """The score of each quiz that was answered, so the page can show it again after a reload."""
        results = {"diagnostic": None, "prerequisite": None}
        for attempt in QuizAttempt.objects.filter(quiz__lesson=lesson).select_related("quiz"):
            summary = {key: attempt.result[key] for key in ("correct", "total", "dont_know", "by_band")}
            if attempt.quiz.kind == Quiz.Kind.DIAGNOSTIC and lesson.route:
                summary["route"] = lesson.route
            results[attempt.quiz.kind] = summary
        return results


class LearnerQuestionSerializer(serializers.Serializer):
    id = serializers.CharField()
    band = serializers.CharField(required=False)
    question = serializers.CharField()
    options = serializers.ListField(child=serializers.CharField())


class QuizForLearnerSerializer(serializers.Serializer):
    quiz_id = serializers.UUIDField()
    kind = serializers.ChoiceField(choices=Quiz.Kind.choices)
    questions = LearnerQuestionSerializer(many=True)
    allow_dont_know = serializers.BooleanField()


class QuizAttemptRequestSerializer(serializers.Serializer):
    answers = serializers.DictField(
        child=serializers.JSONField(), help_text='{question_id: option index 0-3 | "dont_know"}'
    )


class QuizAttemptResponseSerializer(serializers.Serializer):
    result = QuizResultSummarySerializer()
    run_id = serializers.UUIDField()


class ReviewQuestionSerializer(LearnerQuestionSerializer):
    correct_index = serializers.IntegerField()
    explanation = serializers.CharField()
    answer = serializers.JSONField(help_text='The learner\'s answer: an option index or "dont_know".')
    correct = serializers.BooleanField()


class QuizReviewSerializer(serializers.Serializer):
    quiz_id = serializers.UUIDField()
    kind = serializers.ChoiceField(choices=Quiz.Kind.choices)
    questions = ReviewQuestionSerializer(many=True)
    result = serializers.DictField()


class RunSerializer(serializers.ModelSerializer):
    lesson_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = GraphRun
        fields = ["id", "lesson_id", "graph", "trigger", "status", "node_status", "error"]
        read_only_fields = fields


class MaterialKindSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=MaterialKind.choices)


class StudyMaterialSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=MaterialKind.choices)
    content = serializers.DictField(help_text="The sheet (docs/lesson-graph.md). Practice solutions are left out.")
    solutions = serializers.DictField(
        help_text="Practice sheet only: {question_id: solution} for the questions named in `reveal`."
    )


class PracticeGradeRequestSerializer(serializers.Serializer):
    answers = serializers.DictField(
        child=serializers.JSONField(), help_text="{question_id: option index | number | text}"
    )


class PracticeScoreSerializer(serializers.Serializer):
    awarded = serializers.IntegerField()
    available = serializers.IntegerField(help_text="Marks of the questions marked automatically.")
    open_marks = serializers.IntegerField(help_text="Marks of the questions left to self-checking.")
    correct = serializers.IntegerField()
    marked = serializers.IntegerField()


class PracticeResultSerializer(serializers.Serializer):
    id = serializers.CharField()
    correct = serializers.BooleanField(allow_null=True, help_text="null: not marked automatically.")
    marks = serializers.IntegerField()
    awarded = serializers.IntegerField(allow_null=True)
    solution = serializers.DictField()


class PracticeGradeSerializer(serializers.Serializer):
    score = PracticeScoreSerializer()
    results = PracticeResultSerializer(many=True)
