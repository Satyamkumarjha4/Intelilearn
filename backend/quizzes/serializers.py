"""Request and response shapes of the quick quiz API (docs/reference/api.md)."""

from rest_framework import serializers

from graph.questions import QuestionTypes
from graph.questions.presets import QuizPresets
from graph.quiz_config import QuizConfig
from lessons.serializers import (  # noqa: F401  (the quiz's attempts have the lesson test's shapes)
    AnswerRequestSerializer,
    AnswerSavedSerializer,
    AttemptHistorySerializer,
    AttemptStartedSerializer,
    AttemptSubmitSerializer,
    AttemptSummarySerializer,
    ScoreCardSerializer,
    StarsField,
    TestQuestionSerializer,
    TrendSerializer,
)

from .models import QuickQuiz, QuickQuizAttempt
from .stages import QuizStage

LEVEL_MODES = [(mode, mode) for mode in QuizConfig.LEVEL_MODES]


class TopicTraitsRequestSerializer(serializers.Serializer):
    topic = serializers.CharField(min_length=2, max_length=200)
    num_questions = serializers.ChoiceField(
        choices=QuizPresets.COUNTS,
        required=False,
        help_text="The count being considered; the answer does not depend on it.",
    )


class TopicTraitsSerializer(serializers.Serializer):
    numerical = serializers.BooleanField(help_text="Numerical questions make sense for this topic.")
    code = serializers.BooleanField(help_text="Answers to short and long questions may be code.")
    source = serializers.ChoiceField(
        choices=["model", "cache", "fallback"],
        help_text="`fallback`: not judged, so every kind the count allows is offered.",
    )


class QuizSourceSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=QuickQuiz.SourceType.choices)
    topic = serializers.CharField(min_length=2, max_length=200, required=False)
    lesson_ids = serializers.ListField(child=serializers.UUIDField(), required=False, max_length=50)

    def validate(self, attrs: dict) -> dict:
        topic_quiz = attrs["type"] == QuickQuiz.SourceType.TOPIC
        needed, other = ("topic", "lesson_ids") if topic_quiz else ("lesson_ids", "topic")
        if needed not in attrs:
            raise serializers.ValidationError({needed: ["This field is required."]})
        if other in attrs:
            raise serializers.ValidationError(
                {other: [f"This does not go with a quiz about {'a topic' if topic_quiz else 'lessons'}."]}
            )
        return attrs


class QuizLevelSerializer(serializers.Serializer):
    mode = serializers.ChoiceField(choices=LEVEL_MODES)
    rating = StarsField(required=False, help_text="Stars, 0.5 to 5 in half steps. Needed for `self_rating`.")


class QuizCreateSerializer(serializers.Serializer):
    source = QuizSourceSerializer()
    num_questions = serializers.IntegerField(
        help_text="A preset: 5, 10, 15, 20, 25 or 30 (default in the wizard: 10).",
    )
    types = serializers.ListField(
        child=serializers.CharField(),
        help_text=f"Some of {', '.join(QuestionTypes.OFFERED)}. Short and long answers need 10 or more questions; "
        "numerical ones need a quantitative topic.",
    )
    level = QuizLevelSerializer(
        help_text="How the level is found: a self-rating, a calibration quiz, or (for lessons) your test scores."
    )


class QuizCreatedSerializer(serializers.Serializer):
    quiz_id = serializers.UUIDField()
    run_id = serializers.UUIDField()


class QuizConfigSerializer(serializers.Serializer):
    num_questions = serializers.IntegerField()
    types = serializers.ListField(child=serializers.CharField())
    level_mode = serializers.ChoiceField(choices=LEVEL_MODES)
    self_rating = serializers.FloatField(allow_null=True, help_text="Stars, for a self-rated quiz.")


class QuizSourceRowSerializer(serializers.Serializer):
    lesson_id = serializers.UUIDField(allow_null=True, help_text="Null once the lesson was deleted.")
    title = serializers.CharField()
    level = serializers.CharField(help_text="The level of this lesson's questions when its scores set the level.")
    share = serializers.IntegerField(help_text="How many of the quiz's questions are about this lesson.")


class QuizSummarySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    topic = serializers.CharField()
    source_type = serializers.ChoiceField(choices=QuickQuiz.SourceType.choices)
    stage = serializers.ChoiceField(choices=QuizStage.choices)
    level = serializers.CharField(allow_blank=True)
    num_questions = serializers.IntegerField()
    attempts_count = serializers.IntegerField()
    latest_score = serializers.IntegerField(allow_null=True, help_text="Percent of the latest graded attempt.")
    best_score = serializers.IntegerField(allow_null=True)
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()


class OpenAttemptSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    attempt_no = serializers.IntegerField()
    status = serializers.ChoiceField(choices=QuickQuizAttempt.Status.choices)


class QuizDetailSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    topic = serializers.CharField()
    source_type = serializers.ChoiceField(choices=QuickQuiz.SourceType.choices)
    stage = serializers.ChoiceField(choices=QuizStage.choices)
    error = serializers.CharField(allow_blank=True)
    level = serializers.CharField(allow_blank=True, help_text="Empty until the level is known.")
    level_source = serializers.CharField(allow_blank=True, help_text="self_rating, calibration or test_score.")
    config = QuizConfigSerializer()
    sources = QuizSourceRowSerializer(many=True)
    attempts = AttemptSummarySerializer(many=True, help_text="Every attempt, oldest first.")
    trend = TrendSerializer(help_text="The graded attempts of this quiz only: the series and the changes.")
    open_attempt = OpenAttemptSerializer(allow_null=True, help_text="An attempt waiting or in progress.")
    run_id = serializers.UUIDField(allow_null=True, help_text="The run making or retaking the quiz now.")
    can_create_lesson = serializers.BooleanField(help_text="A topic quiz with a graded attempt can become a lesson.")
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()


class CalibrationQuestionSerializer(serializers.Serializer):
    """A calibration question: no band, no answer, no hint of what comes next."""

    id = serializers.CharField()
    question = serializers.CharField(help_text="Markdown; LaTeX between $…$ allowed.")
    options = serializers.ListField(child=serializers.CharField())


class CalibrationSerializer(serializers.Serializer):
    done = serializers.BooleanField()
    step = serializers.IntegerField(required=False, help_text="Which question of the walk this is, from 1.")
    total = serializers.IntegerField(required=False)
    question = CalibrationQuestionSerializer(required=False)
    level = serializers.CharField(required=False, help_text="Once the walk is over.")


class CalibrationAnswerSerializer(serializers.Serializer):
    question_id = serializers.CharField()
    answer = serializers.JSONField(allow_null=True, help_text="The option picked (0 to 3); null: I don't know.")


class RecommendationLinkSerializer(serializers.Serializer):
    concept = serializers.CharField()
    page = serializers.CharField(
        allow_blank=True,
        help_text="introduction, core or advanced: the page of the lesson that teaches the concept. Empty when it "
        "could not be placed: open the lesson as a whole.",
    )
    heading = serializers.CharField(allow_blank=True, help_text="The section on that page; empty with the page.")
    marks_lost = serializers.IntegerField()


class RecommendationLessonSerializer(serializers.Serializer):
    lesson_id = serializers.UUIDField(allow_null=True, help_text="null when the lesson was deleted.")
    title = serializers.CharField()
    level = serializers.CharField()
    marks_lost = serializers.IntegerField()
    topics = serializers.ListField(child=serializers.CharField())
    links = RecommendationLinkSerializer(
        many=True, help_text="`topics` again, each with the page that teaches it and the marks lost on it."
    )
    deleted = serializers.BooleanField(help_text="The lesson was deleted since the quiz was made.")


class RecommendationsSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["topic", "lessons"])
    topics = serializers.ListField(child=serializers.CharField(), help_text="Topic quiz: the concepts to work on.")
    lessons = RecommendationLessonSerializer(
        many=True, help_text="Quiz from lessons: which to study, most marks lost first."
    )


class QuizAttemptSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    attempt_no = serializers.IntegerField()
    status = serializers.ChoiceField(choices=QuickQuizAttempt.Status.choices)
    error = serializers.CharField(allow_blank=True)
    questions = TestQuestionSerializer(
        many=True, help_text="Without answer keys. Empty while the questions are written."
    )
    total_marks = serializers.IntegerField(allow_null=True)
    answers = serializers.DictField(help_text="The learner's own answers, {question_id: answer}.")
    result = ScoreCardSerializer(allow_null=True)
    awarded = serializers.IntegerField(allow_null=True)
    available = serializers.IntegerField(allow_null=True)
    band = serializers.CharField(allow_blank=True)
    duration_s = serializers.IntegerField(allow_null=True)
    recommendations = RecommendationsSerializer(allow_null=True)
    started_at = serializers.DateTimeField()
    submitted_at = serializers.DateTimeField(allow_null=True)
    graded_at = serializers.DateTimeField(allow_null=True)


class QuizSubmittedSerializer(serializers.Serializer):
    attempt_id = serializers.UUIDField()
    attempt_no = serializers.IntegerField()
    run_id = serializers.UUIDField(
        allow_null=True, help_text="The grading run to follow; null when everything was marked."
    )
    status = serializers.ChoiceField(choices=QuickQuizAttempt.Status.choices)
    awarded = serializers.IntegerField(allow_null=True)
    available = serializers.IntegerField(allow_null=True)
    band = serializers.CharField(allow_blank=True)
    result = ScoreCardSerializer(allow_null=True)


class CreateLessonRequestSerializer(serializers.Serializer):
    attempt_id = serializers.UUIDField(help_text="A graded attempt at this quiz.")
