"""Request and response shapes of the lessons API (docs/api.md). Responses are built from the services' output."""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import GraphRun, Lesson, LessonVersion, Quiz, QuizAttempt, TestSubmission
from .stages import MaterialKind, Route


class LessonCreateSerializer(serializers.Serializer):
    topic = serializers.CharField(min_length=2, max_length=200)
    user_context = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")


class LessonCreatedSerializer(serializers.Serializer):
    lesson_id = serializers.UUIDField()
    run_id = serializers.UUIDField()


class RunStartedSerializer(serializers.Serializer):
    run_id = serializers.UUIDField()


class TestScoreSerializer(serializers.Serializer):
    __test__ = False

    awarded = serializers.IntegerField()
    available = serializers.IntegerField()


class LessonSummarySerializer(serializers.ModelSerializer):
    test_status = serializers.SerializerMethodField()
    test_score = serializers.SerializerMethodField()
    material_count = serializers.SerializerMethodField()

    class Meta:
        model = Lesson
        fields = [
            "id", "topic", "stage", "route", "title", "level", "created_at", "updated_at",
            "test_status", "test_score", "material_count",
        ]  # fmt: skip
        read_only_fields = fields

    @staticmethod
    def _submission(lesson: Lesson) -> TestSubmission | None:
        # `.all()` rather than `.first()`: a list prefetches the submissions, and a lesson has at most one.
        submissions = list(lesson.submissions.all())
        return submissions[0] if submissions else None

    @extend_schema_field(serializers.ChoiceField(choices=["not_started", *TestSubmission.Status.values]))
    def get_test_status(self, lesson: Lesson) -> str:
        submission = self._submission(lesson)
        return "not_started" if submission is None else submission.status

    @extend_schema_field(TestScoreSerializer(allow_null=True))
    def get_test_score(self, lesson: Lesson) -> dict | None:
        """Only a finished grading has a score: while it runs, the marks so far are not the result."""
        submission = self._submission(lesson)
        if submission is None or submission.status != TestSubmission.Status.GRADED or not submission.result:
            return None
        score = submission.result["score"]
        return {"awarded": score["awarded"], "available": score["available"]}

    def get_material_count(self, lesson: Lesson) -> int:
        return len(lesson.materials.all())


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
    submitted_at = serializers.DateTimeField(help_text="When the quiz was answered.")


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


class LessonDocumentSerializer(serializers.Serializer):
    code = serializers.CharField(help_text="The TSX document the sandbox runs.")
    code_version = serializers.IntegerField(help_text="Send it back with a repair report so a stale one is refused.")
    has_embedded_test = serializers.BooleanField(
        help_text="A lesson made before the test became its own screen still has it as a page in its code: hide it."
    )
    data = serializers.DictField(help_text="`LESSON`: pages, the test without answers, and media as signed URLs.")


class RepairErrorSerializer(serializers.Serializer):
    message = serializers.CharField(max_length=2000)
    stack = serializers.CharField(max_length=8000, required=False, allow_blank=True)
    page = serializers.CharField(max_length=20, required=False, allow_blank=True)


class RepairRequestSerializer(serializers.Serializer):
    error = RepairErrorSerializer()
    code_version = serializers.IntegerField(min_value=0)


class LessonVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = LessonVersion
        fields = ["code_version", "reason", "created_at"]
        read_only_fields = fields


class RestoredSerializer(serializers.Serializer):
    code_version = serializers.IntegerField(help_text="The new current version.")


class TestSubmitSerializer(serializers.Serializer):
    __test__ = False

    answers = serializers.DictField(
        child=serializers.JSONField(allow_null=True),
        help_text="{question_id: option index | number | text}. Unanswered questions may be left out.",
    )


class TestSubmissionCreatedSerializer(serializers.Serializer):
    __test__ = False

    submission_id = serializers.UUIDField()
    run_id = serializers.UUIDField(
        allow_null=True, help_text="The grading run to follow; null when everything could be marked at once."
    )
    status = serializers.ChoiceField(choices=TestSubmission.Status.choices)


class TestQuestionSerializer(serializers.Serializer):
    """A question as the learner sees it: no answer, marking scheme, explanation or concept."""

    __test__ = False

    id = serializers.CharField()
    type = serializers.ChoiceField(choices=["mcq", "numerical", "short_answer", "long_answer", "code"])
    question = serializers.CharField(help_text="Markdown; LaTeX between $…$ allowed.")
    marks = serializers.IntegerField()
    options = serializers.ListField(child=serializers.CharField(), required=False, help_text="mcq only.")
    unit = serializers.CharField(required=False, help_text="numerical only.")
    language = serializers.CharField(required=False, help_text="code only.")
    starter_code = serializers.CharField(required=False, help_text="code only.")


class TestSubmissionRefSerializer(serializers.Serializer):
    __test__ = False

    id = serializers.UUIDField()
    status = serializers.ChoiceField(choices=TestSubmission.Status.choices)
    submitted_at = serializers.DateTimeField()


class LearnerTestSerializer(serializers.Serializer):
    __test__ = False

    questions = TestQuestionSerializer(many=True)
    total_marks = serializers.IntegerField()
    submission = TestSubmissionRefSerializer(allow_null=True, help_text="null until the test has been submitted.")


class ScoreSerializer(serializers.Serializer):
    awarded = serializers.IntegerField(help_text="Marks earned so far (open-ended answers count once graded).")
    available = serializers.IntegerField(help_text="Marks the whole test is worth.")
    percent = serializers.IntegerField()


class QuestionResultSerializer(serializers.Serializer):
    id = serializers.CharField()
    type = serializers.CharField()
    concept = serializers.CharField()
    marks = serializers.IntegerField()
    awarded = serializers.IntegerField(allow_null=True, help_text="null while a model is still grading it.")
    correct = serializers.BooleanField(allow_null=True)
    graded_by = serializers.ChoiceField(choices=["auto", "model", "none"])
    feedback = serializers.CharField(allow_blank=True)
    solution = serializers.DictField(help_text="The answer, for review after submitting.")


class ScoreCardSerializer(serializers.Serializer):
    complete = serializers.BooleanField(help_text="False while open-ended answers are still being graded.")
    score = ScoreSerializer()
    questions = QuestionResultSerializer(many=True)
    topics_to_revisit = serializers.ListField(child=serializers.CharField())


class TestSubmissionSerializer(serializers.ModelSerializer):
    __test__ = False

    result = ScoreCardSerializer(allow_null=True, read_only=True)
    answers = serializers.DictField(read_only=True, help_text="The learner's own answers, {question_id: answer}.")

    class Meta:
        model = TestSubmission
        fields = ["id", "status", "error", "answers", "result", "submitted_at", "graded_at"]
        read_only_fields = fields
