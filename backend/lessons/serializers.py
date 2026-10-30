"""Request and response shapes of the lessons API (docs/reference/api.md).

Responses are built from the services' output.
"""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from graph.levels import LevelScheme, StarRating
from graph.scoring import AttemptTrend

from .attempts import AttemptQuestions
from .models import GraphRun, Lesson, LessonVersion, Quiz, QuizAttempt, TestSubmission
from .stages import Entry, Intent, LevelSource, MasteryOptions, MaterialKind, Origin, Route


class StarsField(serializers.FloatField):
    """A number of stars. `true` is not one star, which a plain float field would make it."""

    def to_internal_value(self, data):
        if isinstance(data, bool):
            self.fail("invalid")
        return super().to_internal_value(data)


class RecommendedFromSerializer(serializers.Serializer):
    attempt_id = serializers.UUIDField()
    topic = serializers.CharField(max_length=200)


class LessonCreateSerializer(serializers.Serializer):
    topic = serializers.CharField(min_length=2, max_length=200)
    user_context = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")
    entry = serializers.ChoiceField(
        choices=[Entry.DIAGNOSTIC, Entry.SELF_RATING],
        default=Entry.DIAGNOSTIC,
        help_text="How the learner's level is found: a quick check (`diagnostic`) or their own rating (`self_rating`).",
    )
    self_rating = StarsField(
        required=False, min_value=0.5, max_value=5, help_text="Stars, 0.5 to 5 in half steps. Needed for `self_rating`."
    )
    intent = serializers.ChoiceField(
        choices=[Intent.LESSON], default=Intent.LESSON, help_text="Only a lesson can be asked for for now."
    )
    origin = serializers.ChoiceField(
        choices=Origin.choices,
        default=Origin.DIRECT,
        help_text="Checked by the server: `direct` or `recommendation`. The others are refused for now.",
    )
    recommended_from = RecommendedFromSerializer(
        required=False, help_text="For `recommendation`: the learner's own graded attempt and one of its topics."
    )

    def validate(self, attrs: dict) -> dict:
        rating = attrs.pop("self_rating", None)
        if attrs["entry"] == Entry.SELF_RATING:
            if rating is None:
                raise serializers.ValidationError({"self_rating": ["Rate yourself from 0.5 to 5 stars."]})
            try:
                attrs["self_rating_halves"] = StarRating.from_stars(rating).halves
            except ValueError:
                raise serializers.ValidationError({"self_rating": ["Stars go in steps of half a star."]}) from None
        elif rating is not None:
            raise serializers.ValidationError({"self_rating": ["A rating goes with `entry: self_rating`."]})
        return attrs


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
    latest_score = serializers.SerializerMethodField()
    best_score = serializers.SerializerMethodField()
    attempts_count = serializers.SerializerMethodField()
    has_open_attempt = serializers.SerializerMethodField()
    material_count = serializers.SerializerMethodField()

    class Meta:
        model = Lesson
        fields = [
            "id", "topic", "stage", "route", "title", "level", "created_at", "updated_at",
            "test_status", "test_score", "latest_score", "best_score", "attempts_count", "has_open_attempt",
            "material_count",
        ]  # fmt: skip
        read_only_fields = fields

    @staticmethod
    def _attempts(lesson: Lesson) -> list[TestSubmission]:
        # `.all()` rather than a query: a list prefetches the attempts. Newest first (`TestSubmission.Meta.ordering`).
        return list(lesson.submissions.all())

    @classmethod
    def _graded(cls, lesson: Lesson) -> list[TestSubmission]:
        """Only a finished grading has a score: while it runs, the marks so far are not the result."""
        return [a for a in cls._attempts(lesson) if a.status == TestSubmission.Status.GRADED and a.result]

    @staticmethod
    def _score(attempt: TestSubmission) -> dict:
        score = attempt.result["score"]
        return {"awarded": score["awarded"], "available": score["available"]}

    @extend_schema_field(serializers.ChoiceField(choices=["not_started", *TestSubmission.Status.values]))
    def get_test_status(self, lesson: Lesson) -> str:
        """How the latest attempt stands."""
        attempts = self._attempts(lesson)
        return "not_started" if not attempts else attempts[0].status

    @extend_schema_field(TestScoreSerializer(allow_null=True))
    def get_test_score(self, lesson: Lesson) -> dict | None:
        return self.get_latest_score(lesson)

    @extend_schema_field(TestScoreSerializer(allow_null=True))
    def get_latest_score(self, lesson: Lesson) -> dict | None:
        """The score of the latest graded attempt (a retake that is still open does not hide it)."""
        graded = self._graded(lesson)
        return self._score(graded[0]) if graded else None

    @extend_schema_field(TestScoreSerializer(allow_null=True))
    def get_best_score(self, lesson: Lesson) -> dict | None:
        """The best graded attempt by percent; of two equal ones the earlier."""
        graded = self._graded(lesson)
        if not graded:
            return None
        best = max(
            reversed(graded),
            key=lambda a: AttemptTrend.percent(a.result["score"]["awarded"], a.result["score"]["available"]),
        )
        return self._score(best)

    def get_attempts_count(self, lesson: Lesson) -> int:
        return sum(1 for a in self._attempts(lesson) if a.status != TestSubmission.Status.GENERATING)

    def get_has_open_attempt(self, lesson: Lesson) -> bool:
        return any(a.is_open for a in self._attempts(lesson))

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
    source = serializers.ChoiceField(
        choices=LevelSource.choices, required=False, help_text="Where the level came from; absent on an old lesson."
    )
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
    entry = serializers.ChoiceField(choices=Entry.choices, read_only=True)
    intent = serializers.ChoiceField(choices=Intent.choices, read_only=True)
    origin = serializers.ChoiceField(choices=Origin.choices, read_only=True)
    level_source = serializers.ChoiceField(choices=LevelSource.choices, read_only=True)
    mastery_options = serializers.ChoiceField(
        choices=MasteryOptions.choices,
        read_only=True,
        help_text="What the choice after a perfect quick check offers: the Expert lesson or two sheets, or (a lesson "
        "that was already waiting) the three sheets.",
    )
    self_rating = serializers.SerializerMethodField()

    class Meta(LessonSummarySerializer.Meta):
        fields = [
            *LessonSummarySerializer.Meta.fields,
            "entry",
            "intent",
            "origin",
            "level_source",
            "mastery_options",
            "self_rating",
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

    @extend_schema_field(serializers.FloatField(allow_null=True, help_text="Stars, 0.5 to 5; null unless self-rated."))
    def get_self_rating(self, lesson: Lesson) -> float | None:
        return None if lesson.self_rating_halves is None else lesson.self_rating_halves / 2

    def get_assessment(self, lesson: Lesson) -> dict | None:
        if not lesson.assessment:
            return None
        return AssessmentSerializer(LevelScheme.upgraded(lesson.assessment)).data

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


class MasteryChoiceSerializer(serializers.Serializer):
    """The pick after a perfect quick check: `choice`, or (for a lesson already waiting at the old three-sheet choice)
    one sheet `kind`."""

    choice = serializers.ChoiceField(choices=["lesson", "sheets"], required=False)
    kind = serializers.ChoiceField(choices=MaterialKind.choices, required=False)

    def validate(self, attrs: dict) -> dict:
        if ("choice" in attrs) == ("kind" in attrs):
            raise serializers.ValidationError({"choice": ["Send `choice`: lesson or sheets."]})
        return {"choice": attrs.get("choice") or attrs["kind"]}


class StudyMaterialSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=MaterialKind.choices)
    content = serializers.DictField(
        help_text="The sheet (docs/architecture/lesson-graph.md). Practice solutions are left out."
    )
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
        help_text="{question_id: option index | list of option indices | number | text}. Unanswered questions may be "
        "left out.",
    )


class AttemptSubmitSerializer(serializers.Serializer):
    answers = serializers.DictField(
        child=serializers.JSONField(allow_null=True),
        required=False,
        help_text="Answers to questions that are not locked yet, sent with the submit (the last card). A locked "
        "question keeps the answer it was saved with.",
    )


class TestQuestionSerializer(serializers.Serializer):
    """A question as the learner sees it: no answer, marking scheme, explanation or concept."""

    __test__ = False

    id = serializers.CharField()
    type = serializers.ChoiceField(choices=["mcq", "msq", "numerical", "short_answer", "long_answer", "code"])
    question = serializers.CharField(help_text="Markdown; LaTeX between $…$ allowed.")
    marks = serializers.IntegerField()
    options = serializers.ListField(child=serializers.CharField(), required=False, help_text="mcq and msq.")
    unit = serializers.CharField(required=False, help_text="numerical only.")
    decimal_precision = serializers.IntegerField(required=False, help_text="numerical only: a hint, never a rule.")
    language = serializers.CharField(required=False, help_text="code only.")
    starter_code = serializers.CharField(required=False, help_text="code only.")


class AttemptRefSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    attempt_no = serializers.IntegerField()
    status = serializers.ChoiceField(choices=TestSubmission.Status.choices)
    started_at = serializers.DateTimeField()
    submitted_at = serializers.DateTimeField(allow_null=True)


class TestSubmissionRefSerializer(serializers.Serializer):
    __test__ = False

    id = serializers.UUIDField()
    status = serializers.ChoiceField(choices=TestSubmission.Status.choices)
    submitted_at = serializers.DateTimeField(allow_null=True)


class LearnerTestSerializer(serializers.Serializer):
    __test__ = False

    questions = TestQuestionSerializer(many=True, help_text="The open attempt's questions; none while there is none.")
    total_marks = serializers.IntegerField()
    attempt = AttemptRefSerializer(allow_null=True, help_text="The open attempt (generating or in progress).")
    answers = serializers.DictField(help_text="The open attempt's saved (locked) answers, so a refresh resumes.")
    next_attempt_no = serializers.IntegerField(help_text="The number the next attempt will have.")
    submission = TestSubmissionRefSerializer(allow_null=True, help_text="The latest attempt; null before the first.")


class AttemptStartedSerializer(serializers.Serializer):
    attempt_id = serializers.UUIDField()
    attempt_no = serializers.IntegerField()
    status = serializers.ChoiceField(choices=[TestSubmission.Status.GENERATING, TestSubmission.Status.IN_PROGRESS])
    run_id = serializers.UUIDField(allow_null=True, help_text="The run preparing a retake's questions; else null.")
    questions = TestQuestionSerializer(many=True, help_text="Empty while the questions are being prepared.")
    total_marks = serializers.IntegerField()
    answers = serializers.DictField(help_text="Answers already saved (locked) when an open attempt is resumed.")
    started_at = serializers.DateTimeField()


class AnswerSavedSerializer(serializers.Serializer):
    attempt_id = serializers.UUIDField()
    question_id = serializers.CharField()
    locked = serializers.BooleanField()
    answered = serializers.IntegerField(help_text="How many questions of the attempt are locked.")


class AnswerRequestSerializer(serializers.Serializer):
    answer = serializers.JSONField(
        allow_null=True, help_text="An option index, a list of option indices, a number or text. null: left blank."
    )


class ScoreSerializer(serializers.Serializer):
    awarded = serializers.IntegerField(help_text="Marks earned so far (open-ended answers count once graded).")
    available = serializers.IntegerField(help_text="Marks the whole test is worth.")
    percent = serializers.IntegerField()


class CriterionResultSerializer(serializers.Serializer):
    text = serializers.CharField()
    marks = serializers.IntegerField()
    awarded = serializers.IntegerField()


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
    criteria = CriterionResultSerializer(many=True, required=False, help_text="Open-ended answers graded by a model.")


class ScoreCardSerializer(serializers.Serializer):
    complete = serializers.BooleanField(help_text="False while open-ended answers are still being graded.")
    score = ScoreSerializer()
    questions = QuestionResultSerializer(many=True)
    topics_to_revisit = serializers.ListField(child=serializers.CharField())


class TestSubmissionCreatedSerializer(serializers.Serializer):
    """The reply to a submit. A lesson attempt is graded in full, so its score, band and offer come with it."""

    __test__ = False

    submission_id = serializers.UUIDField()
    attempt_id = serializers.UUIDField(required=False)
    attempt_no = serializers.IntegerField(required=False)
    run_id = serializers.UUIDField(
        allow_null=True, help_text="The grading run to follow; null when everything could be marked at once."
    )
    status = serializers.ChoiceField(choices=TestSubmission.Status.choices)
    awarded = serializers.IntegerField(allow_null=True, required=False)
    available = serializers.IntegerField(allow_null=True, required=False)
    band = serializers.CharField(required=False, allow_blank=True, help_text="fail, normal or excellent once graded.")
    followup = serializers.DictField(allow_null=True, required=False, help_text="The offer that follows the score.")
    result = ScoreCardSerializer(allow_null=True, required=False)


class TestSubmissionSerializer(serializers.ModelSerializer):
    __test__ = False

    result = ScoreCardSerializer(allow_null=True, read_only=True)
    answers = serializers.DictField(read_only=True, help_text="The learner's own answers, {question_id: answer}.")
    questions = serializers.SerializerMethodField(
        help_text="What the attempt asked, without answer keys, for the read-only result. Empty while it is open: "
        "`GET /lessons/{id}/test` serves the open attempt's questions."
    )

    class Meta:
        model = TestSubmission
        fields = [
            "id", "attempt_no", "status", "error", "questions", "answers", "result", "awarded", "available", "band",
            "duration_s", "followup", "started_at", "submitted_at", "graded_at",
        ]  # fmt: skip
        read_only_fields = fields

    @extend_schema_field(TestQuestionSerializer(many=True))
    def get_questions(self, attempt: TestSubmission) -> list[dict]:
        return AttemptQuestions.of_sealed(attempt)


class AttemptSummarySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    attempt_no = serializers.IntegerField()
    status = serializers.ChoiceField(choices=TestSubmission.Status.choices)
    awarded = serializers.IntegerField(allow_null=True)
    available = serializers.IntegerField(allow_null=True)
    percent = serializers.IntegerField(allow_null=True)
    band = serializers.CharField(allow_blank=True)
    duration_s = serializers.IntegerField(allow_null=True)
    submitted_at = serializers.DateTimeField(allow_null=True)


class TrendPointSerializer(serializers.Serializer):
    attempt_no = serializers.IntegerField()
    awarded = serializers.IntegerField()
    available = serializers.IntegerField()
    percent = serializers.IntegerField()
    delta_previous = serializers.IntegerField(
        allow_null=True, help_text="Percentage points since the previous attempt."
    )
    delta_best = serializers.IntegerField(allow_null=True, help_text="Percentage points against the best earlier one.")


class TrendSerializer(serializers.Serializer):
    series = TrendPointSerializer(many=True)
    best_attempt_no = serializers.IntegerField(allow_null=True)


class AttemptHistorySerializer(serializers.Serializer):
    attempts = AttemptSummarySerializer(many=True)
    trend = TrendSerializer()
