"""Unit under test: the Stage A nodes in `graph.nodes.diagnose`: loading context, generating and validating the
diagnostic, publishing the quizzes, grading and routing, and assessing the learner.

Why: these nodes turn a learner's answers into the plan for their lesson. A node that forgets the stage change leaves
the browser on the wrong screen; one that trusts the model's prerequisites over the graded ones builds the wrong
lesson; one that spends its retries badly either loops or gives up early.

Use cases:
- load_context reads the topic, the profile (without name or email) and the snapshots from the lesson
- generate_diagnostic asks the model for a DiagnosticBundle and counts the attempt
- a node that runs while the lesson is failed (a retry) moves it back to the node's working stage, and only then
- generate_diagnostic passes the validator's problems to the model as feedback on a retry
- validate_diagnostic accepts a good bundle and clears the feedback
- validate_diagnostic keeps the problems and announces another attempt while attempts remain
- validate_diagnostic sets the error, the node to resume at and the counters to reset when attempts run out
- the optional reviewer never fails a lesson: when none of its models answer it is skipped with a warning, and when
  the attempts are spent while every rule passes and only the reviewer objects, the quiz is kept with a warning
- validate_diagnostic asks the optional reviewer only after the deterministic rules pass, and only if it is enabled
- publish_diagnostic stores the quiz and moves the lesson to awaiting_diagnostic (and is safe to run twice)
- publish_prerequisite stores the prerequisite quiz with its prerequisites
- grade_diagnostic routes by the stored result and records the route on the lesson
- grade_diagnostic moves a lesson-route learner straight to generating_lesson
- grade_prerequisite turns the stored result into the prerequisites to cover
- assess_learner asks for a LearnerAssessment, overrides the model's prerequisites, and saves the assessment
"""

import pytest
from support.quiz_data import make_prerequisites, make_questions

from graph.grading import QuizGrader
from graph.nodes.diagnose import (
    AssessLearnerNode,
    GenerateDiagnosticNode,
    GradeDiagnosticNode,
    GradePrerequisiteNode,
    LoadContextNode,
    PublishDiagnosticNode,
    PublishPrerequisiteNode,
    ValidateDiagnosticNode,
)
from graph.schemas import DiagnosticBundle, LearnerAssessment, QuizReview
from lessons.models import Lesson, Quiz, QuizAttempt, Stage
from llm_registry.gateway import AllModelsFailed


def answers_for(questions, right: int) -> dict:
    return {q["id"]: q["correct_index"] if n < right else (q["correct_index"] + 1) % 4 for n, q in enumerate(questions)}


def attempt_for(lesson, kind, questions, right, prerequisites=None):
    quiz, _ = Quiz.objects.update_or_create(
        lesson=lesson, kind=kind, defaults={"questions": questions, "prerequisites": prerequisites}
    )
    answers = answers_for(questions, right)
    return QuizAttempt.objects.create(
        quiz=quiz, answers=answers, result=QuizGrader().grade(questions, answers).as_dict()
    )


class TestLoadContext:
    def test_reads_topic_profile_and_snapshots_from_the_lesson(self, lesson, user, runtime):
        user.profile.education_level = "undergraduate"
        user.profile.goal = "exam_prep"
        user.profile.preferred_language = "hi"
        user.profile.notes = "I know arrays"
        user.profile.save()
        Lesson.objects.filter(pk=lesson.pk).update(
            user_context="for my exam",
            config_snapshot={"version": 1},
            settings_snapshot={"prereq_trigger_max_correct": 2},
        )

        update = LoadContextNode()({"lesson_id": str(lesson.id)}, runtime)

        assert update["topic"] == "Binary search"
        assert update["user_context"] == "for my exam"
        assert update["snapshot"] == {"version": 1}
        assert update["settings"] == {"prereq_trigger_max_correct": 2}
        assert update["profile"]["education_level"] == "Undergraduate"
        assert update["profile"]["goal"] == "Exam preparation"
        assert update["profile"]["preferred_language"] == "hi"
        assert update["profile"]["notes"] == "I know arrays"

    def test_never_puts_the_name_or_email_in_the_profile(self, lesson, runtime):
        update = LoadContextNode()({"lesson_id": str(lesson.id)}, runtime)

        assert "ada@example.com" not in str(update) and "Lovelace" not in str(update)


class TestGenerateDiagnostic:
    def test_asks_the_model_for_a_bundle_and_counts_the_attempt(
        self, lesson, lesson_state, gateway, runtime, valid_bundle
    ):
        gateway.script("diagnostic.generate", valid_bundle)

        update = GenerateDiagnosticNode()(lesson_state, runtime)

        assert update["bundle"] == DiagnosticBundle.model_validate(valid_bundle).model_dump(mode="json")
        assert update["attempts"] == {"diagnostic": 1}
        call = gateway.called("diagnostic.generate")[0]
        assert call.schema is DiagnosticBundle
        assert call.snapshot is lesson_state["snapshot"]
        assert call.run_id == "run-1"

    def test_passes_the_validators_problems_to_the_model_on_a_retry(self, lesson_state, gateway, runtime, valid_bundle):
        gateway.script("diagnostic.generate", valid_bundle)
        state = lesson_state | {"feedback": {"diagnostic": ["Use exactly 10 questions."]}}

        GenerateDiagnosticNode()(state, runtime)

        user_message = gateway.called("diagnostic.generate")[0].messages[1].content
        assert "- Use exactly 10 questions." in user_message

    def test_announces_itself_to_the_progress_stream(self, lesson_state, gateway, runtime, events, valid_bundle):
        gateway.script("diagnostic.generate", valid_bundle)

        GenerateDiagnosticNode()(lesson_state, runtime)

        assert {"type": "node", "node": "generate_diagnostic", "status": "running"} in events.events

    def test_a_retry_after_failure_moves_the_lesson_back_to_preparing(
        self, lesson, lesson_state, gateway, runtime, valid_bundle
    ):
        lesson.fail("The diagnostic quiz still failed its checks")
        gateway.script("diagnostic.generate", valid_bundle)

        GenerateDiagnosticNode()(lesson_state, runtime)

        stored = Lesson.objects.get(pk=lesson.pk)
        assert (stored.stage, stored.error) == (Stage.PREPARING_DIAGNOSTIC, "")

    def test_leaves_the_stage_alone_unless_the_lesson_failed(
        self, lesson, lesson_state, gateway, runtime, valid_bundle
    ):
        Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.AWAITING_DIAGNOSTIC)
        gateway.script("diagnostic.generate", valid_bundle)

        GenerateDiagnosticNode()(lesson_state, runtime)

        assert Lesson.objects.get(pk=lesson.pk).stage == Stage.AWAITING_DIAGNOSTIC


class TestValidateDiagnostic:
    def state(self, lesson_state, bundle, **extra):
        return lesson_state | {"bundle": bundle} | extra

    def test_accepts_a_good_bundle_and_clears_the_feedback(self, lesson_state, runtime, valid_bundle):
        update = ValidateDiagnosticNode()(self.state(lesson_state, valid_bundle), runtime)

        assert update == {"feedback": {"diagnostic": []}}

    def test_keeps_the_problems_and_announces_another_attempt_while_attempts_remain(
        self, lesson_state, runtime, events, valid_bundle
    ):
        valid_bundle["diagnostic"].pop()
        state = self.state(lesson_state, valid_bundle, attempts={"diagnostic": 1})

        update = ValidateDiagnosticNode()(state, runtime)

        assert update["feedback"]["diagnostic"] and "error" not in update
        attempt = events.of_type("attempt")[0]
        assert (attempt["node"], attempt["attempt"]) == ("generate_diagnostic", 2)

    def test_gives_up_when_the_attempts_are_spent(self, lesson_state, runtime, valid_bundle):
        valid_bundle["diagnostic"].pop()
        state = self.state(lesson_state, valid_bundle, attempts={"diagnostic": 2})

        update = ValidateDiagnosticNode()(state, runtime)

        assert update["error"].startswith("The diagnostic quiz still failed its checks after 2 attempts:")
        assert update["failed_node"] == "generate_diagnostic"
        assert update["retry_keys"] == ["diagnostic"]

    def test_the_attempt_budget_comes_from_the_node_config(
        self, lesson_state, runtime, valid_bundle, make_snapshot_for_nodes
    ):
        valid_bundle["diagnostic"].pop()
        state = self.state(
            lesson_state, valid_bundle, attempts={"diagnostic": 1}, snapshot=make_snapshot_for_nodes(attempts=1)
        )

        assert "error" in ValidateDiagnosticNode()(state, runtime)

    def test_the_error_names_at_most_four_problems(self, lesson_state, runtime, valid_bundle):
        valid_bundle["diagnostic"] = valid_bundle["diagnostic"][:3]
        state = self.state(lesson_state, valid_bundle, attempts={"diagnostic": 2})

        update = ValidateDiagnosticNode()(state, runtime)

        assert update["error"].endswith(" …")

    def test_checks_latex_through_the_sandbox(self, lesson_state, runtime, sandbox, valid_bundle):
        valid_bundle["diagnostic"][0]["question"] = "Evaluate $x^2$."
        sandbox.latex_errors = ["LaTeX does not parse: 'x^2'"]

        update = ValidateDiagnosticNode()(self.state(lesson_state, valid_bundle), runtime)

        assert update["feedback"]["diagnostic"] == ["LaTeX does not parse: 'x^2'"]

    def test_asks_the_reviewer_when_it_is_enabled_and_the_rules_pass(
        self, lesson_state, runtime, gateway, valid_bundle, make_snapshot_for_nodes
    ):
        gateway.script("diagnostic.review", {"issues": [{"question_id": "q10", "problem": "Answerable from wording."}]})
        state = self.state(lesson_state, valid_bundle, snapshot=make_snapshot_for_nodes(disabled=()))

        update = ValidateDiagnosticNode()(state, runtime)

        assert update["feedback"]["diagnostic"] == ["Question q10: Answerable from wording."]
        assert gateway.called("diagnostic.review")[0].schema is QuizReview

    def test_skips_the_reviewer_when_the_rules_already_fail(
        self, lesson_state, runtime, gateway, valid_bundle, make_snapshot_for_nodes
    ):
        valid_bundle["diagnostic"].pop()
        state = self.state(lesson_state, valid_bundle, snapshot=make_snapshot_for_nodes(disabled=()))

        ValidateDiagnosticNode()(state, runtime)

        assert gateway.called("diagnostic.review") == []

    def test_skips_the_reviewer_when_it_has_no_model(self, lesson_state, runtime, gateway, valid_bundle):
        ValidateDiagnosticNode()(self.state(lesson_state, valid_bundle), runtime)

        assert gateway.called("diagnostic.review") == []

    def test_skips_a_reviewer_whose_models_all_failed_and_says_so(
        self, lesson_state, runtime, gateway, valid_bundle, make_snapshot_for_nodes, events
    ):
        gateway.scripts["diagnostic.review"] = [AllModelsFailed("diagnostic.review", ["gemini: 429"])]
        state = self.state(lesson_state, valid_bundle, snapshot=make_snapshot_for_nodes(disabled=()))

        update = ValidateDiagnosticNode()(state, runtime)

        assert update == {
            "feedback": {"diagnostic": []},
            "warnings": ["The quiz review was skipped: none of its models answered."],
        }
        assert events.of_type("warning")[0]["message"].startswith("The quiz review was skipped")

    def test_keeps_the_quiz_when_only_the_reviewer_objects_after_the_last_attempt(
        self, lesson_state, runtime, gateway, valid_bundle, make_snapshot_for_nodes
    ):
        gateway.script("diagnostic.review", {"issues": [{"question_id": "q10", "problem": "Answerable from wording."}]})
        state = self.state(
            lesson_state, valid_bundle, snapshot=make_snapshot_for_nodes(disabled=()), attempts={"diagnostic": 2}
        )

        update = ValidateDiagnosticNode()(state, runtime)

        assert update["feedback"] == {"diagnostic": []} and "error" not in update
        assert update["warnings"] == ["The quiz reviewer still had concerns: Question q10: Answerable from wording."]

    def test_a_rule_that_fails_on_the_last_attempt_still_fails_the_run_even_with_a_reviewer(
        self, lesson_state, runtime, gateway, valid_bundle, make_snapshot_for_nodes
    ):
        valid_bundle["diagnostic"].pop()
        state = self.state(
            lesson_state, valid_bundle, snapshot=make_snapshot_for_nodes(disabled=()), attempts={"diagnostic": 2}
        )

        update = ValidateDiagnosticNode()(state, runtime)

        assert update["error"].startswith("The diagnostic quiz still failed its checks")
        assert gateway.called("diagnostic.review") == []

    def test_accepts_when_the_enabled_reviewer_finds_nothing(
        self, lesson_state, runtime, gateway, valid_bundle, make_snapshot_for_nodes
    ):
        gateway.script("diagnostic.review", {"issues": []})
        state = self.state(lesson_state, valid_bundle, snapshot=make_snapshot_for_nodes(disabled=()))

        assert ValidateDiagnosticNode()(state, runtime) == {"feedback": {"diagnostic": []}}


class TestPublish:
    def test_publish_diagnostic_stores_the_quiz_and_moves_to_awaiting(
        self, lesson, lesson_state, runtime, valid_bundle
    ):
        update = PublishDiagnosticNode()(lesson_state | {"bundle": valid_bundle}, runtime)

        quiz = Quiz.objects.get(lesson=lesson, kind="diagnostic")
        assert update == {"diagnostic_quiz_id": str(quiz.id)}
        assert quiz.questions == valid_bundle["diagnostic"]
        assert Lesson.objects.get(pk=lesson.pk).stage == Stage.AWAITING_DIAGNOSTIC

    def test_publish_diagnostic_is_safe_to_run_twice(self, lesson, lesson_state, runtime, valid_bundle):
        state = lesson_state | {"bundle": valid_bundle}
        first = PublishDiagnosticNode()(state, runtime)

        second = PublishDiagnosticNode()(state, runtime)

        assert first == second
        assert Quiz.objects.filter(lesson=lesson).count() == 1

    def test_publish_prerequisite_stores_questions_and_prerequisites(self, lesson, lesson_state, runtime, valid_bundle):
        Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.AWAITING_DIAGNOSTIC)

        update = PublishPrerequisiteNode()(lesson_state | {"bundle": valid_bundle}, runtime)

        quiz = Quiz.objects.get(lesson=lesson, kind="prerequisite")
        assert update == {"prerequisite_quiz_id": str(quiz.id)}
        assert quiz.questions == valid_bundle["prerequisite_questions"]
        assert quiz.prerequisites == valid_bundle["prerequisites"]
        assert Lesson.objects.get(pk=lesson.pk).stage == Stage.AWAITING_PREREQUISITE


class TestGradeDiagnostic:
    @pytest.mark.parametrize(
        ("right", "route"), [(0, "prerequisite"), (2, "prerequisite"), (5, "lesson"), (10, "mastery")]
    )
    def test_routes_by_the_stored_result(self, lesson, lesson_state, runtime, right, route):
        Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.AWAITING_DIAGNOSTIC)
        attempt = attempt_for(lesson, "diagnostic", make_questions(), right)

        update = GradeDiagnosticNode()(lesson_state | {"diagnostic_attempt_id": str(attempt.id)}, runtime)

        assert update["route"] == route
        assert update["diagnostic_result"]["correct"] == right
        assert update["prerequisites_to_cover"] == []
        assert Lesson.objects.get(pk=lesson.pk).route == route

    def test_the_lesson_route_goes_straight_to_generating_the_lesson(self, lesson, lesson_state, runtime):
        Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.AWAITING_DIAGNOSTIC)
        attempt = attempt_for(lesson, "diagnostic", make_questions(), 5)

        GradeDiagnosticNode()(lesson_state | {"diagnostic_attempt_id": str(attempt.id)}, runtime)

        assert Lesson.objects.get(pk=lesson.pk).stage == Stage.GENERATING_LESSON

    def test_the_other_routes_leave_the_stage_for_the_next_publish_node(self, lesson, lesson_state, runtime):
        Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.AWAITING_DIAGNOSTIC)
        attempt = attempt_for(lesson, "diagnostic", make_questions(), 0)

        GradeDiagnosticNode()(lesson_state | {"diagnostic_attempt_id": str(attempt.id)}, runtime)

        assert Lesson.objects.get(pk=lesson.pk).stage == Stage.AWAITING_DIAGNOSTIC

    def test_uses_the_lessons_settings_snapshot(self, lesson, lesson_state, runtime):
        Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.AWAITING_DIAGNOSTIC)
        attempt = attempt_for(lesson, "diagnostic", make_questions(), 3)
        state = lesson_state | {"diagnostic_attempt_id": str(attempt.id)}
        state["settings"] = state["settings"] | {"prereq_trigger_max_correct": 3}

        assert GradeDiagnosticNode()(state, runtime)["route"] == "prerequisite"


class TestGradePrerequisite:
    @pytest.mark.parametrize(("right", "covered"), [(0, 5), (3, 2), (5, 0)])
    def test_covers_the_prerequisites_that_were_missed(self, lesson, lesson_state, runtime, right, covered):
        Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.AWAITING_PREREQUISITE)
        prerequisites, questions = make_prerequisites()
        attempt = attempt_for(lesson, "prerequisite", questions, right, prerequisites)

        update = GradePrerequisiteNode()(lesson_state | {"prerequisite_attempt_id": str(attempt.id)}, runtime)

        assert len(update["prerequisites_to_cover"]) == covered
        assert update["prerequisite_result"]["correct"] == right
        stored = Lesson.objects.get(pk=lesson.pk)
        assert (stored.stage, len(stored.prerequisites_to_cover)) == (Stage.GENERATING_LESSON, covered)


class TestAssessLearner:
    ASSESSMENT = {
        "level": "beginner",
        "known_concepts": ["a"],
        "gaps": ["b"],
        "prerequisites_to_cover": ["invented by the model"],
        "start_point": "Halving",
        "author_notes": "Be gentle.",
        "confidence": "high",
    }

    def state(self, lesson_state, valid_bundle, to_cover):
        result = QuizGrader().grade(valid_bundle["diagnostic"], answers_for(valid_bundle["diagnostic"], 6)).as_dict()
        return lesson_state | {"bundle": valid_bundle, "diagnostic_result": result, "prerequisites_to_cover": to_cover}

    def test_overrides_the_prerequisites_with_the_graded_ones_and_saves_the_assessment(
        self, lesson, lesson_state, gateway, runtime, valid_bundle
    ):
        Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.GENERATING_LESSON)
        gateway.script("learner.assess", self.ASSESSMENT)
        to_cover = [{"name": "Arrays", "why_needed": "x"}]

        update = AssessLearnerNode()(self.state(lesson_state, valid_bundle, to_cover), runtime)

        assert update["assessment"]["prerequisites_to_cover"] == ["Arrays"]
        assert update["assessment"]["start_point"] == "Halving"
        assert gateway.called("learner.assess")[0].schema is LearnerAssessment
        stored = Lesson.objects.get(pk=lesson.pk)
        assert stored.assessment == update["assessment"]
        assert stored.level == "beginner"

    def test_sends_the_quiz_results_but_never_the_answers_to_the_model(
        self, lesson, lesson_state, gateway, runtime, valid_bundle
    ):
        Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.GENERATING_LESSON)
        gateway.script("learner.assess", self.ASSESSMENT)

        AssessLearnerNode()(self.state(lesson_state, valid_bundle, []), runtime)

        user_message = gateway.called("learner.assess")[0].messages[1].content
        assert "6/10 correct" in user_message
        assert "correct_index" not in user_message
