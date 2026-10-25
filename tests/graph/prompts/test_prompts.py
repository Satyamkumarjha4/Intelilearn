"""Unit under test: the `graph.prompts` package, one `Prompt` subclass per LLM node, all built on `Prompt`.

Why: a prompt that drops the rejected-attempt feedback makes every retry repeat the same mistake; one that omits the
language rule writes the lesson in the wrong language; one that leaks the answers to the assessor or the browser
corrupts the diagnostic. Every node's prompt is exercised so a refactor cannot silently break one.

Use cases:
- every prompt produces a system and a user message
- the rejected-attempt feedback is added to the user message when given, and absent otherwise
- learner-facing prompts state the learner's preferred language (English by default)
- the topic and what the learner said about it reach the model
- the diagnostic prompt states the counts from the settings and the band meanings
- the review prompt includes the answers (it must judge them); the assessment prompt shows only right/wrong
- the assessment prompt asks the model to copy the deterministic prerequisites, and includes the prerequisite quiz
  only when there was one
- the study prompt carries the instructions for the chosen sheet and the concepts to cover
- the media verification prompt is a single multimodal message with the image
- the code prompts carry the sandbox scope contract
"""

import pytest
from langchain_core.messages import HumanMessage, SystemMessage
from support.lesson_data import make_state
from support.quiz_data import make_prerequisites, make_questions

from graph.grading import QuizGrader
from graph.prompts import (
    SCOPE_REFERENCE,
    AlignmentPrompt,
    AssessLearnerPrompt,
    CompilePagePrompt,
    DiagnosticPrompt,
    DiagnosticReviewPrompt,
    GenerateInteractivePrompt,
    MediaAgentPrompt,
    PlanInteractivesPrompt,
    PlanLessonPrompt,
    RepairCodePrompt,
    RuntimeRepairPrompt,
    StudyMaterialPrompt,
    VerifyMediaPrompt,
    WritePagePrompt,
    WriteTestPrompt,
)

QUESTIONS = make_questions()
PREREQUISITES, PREREQUISITE_QUESTIONS = make_prerequisites()
GRADER = QuizGrader()


def subject() -> dict:
    """A state with everything any prompt reads."""
    state = make_state()
    spec = state["interactive_plan"]["specs"][0]
    all_right = {q["id"]: q["correct_index"] for q in QUESTIONS}
    return state | {
        "bundle": {
            "diagnostic": QUESTIONS,
            "prerequisites": PREREQUISITES,
            "prerequisite_questions": PREREQUISITE_QUESTIONS,
        },  # fmt: skip
        "diagnostic_questions": QUESTIONS,
        "prerequisite_questions": PREREQUISITE_QUESTIONS,
        "diagnostic_result": GRADER.grade(QUESTIONS, all_right).as_dict(),
        "kind": "cheat_sheet",
        "concepts": ["Halving the range", "Time complexity"],
        "page_plan": state["plan"]["pages"][1],
        "spec": spec,
        "component_name": "Interactive_widget_introduction",
        "section": state["pages"]["introduction"]["sections"][0],
        "key": "core",
        "components": [{"name": "Interactive_widget_core", "anchor": "s1", "purpose": "Shows halving."}],
        "figures": [{"asset": "asset-1", "anchor": "s2", "caption": "A caption"}],
        "tools_available": ["search_wikimedia", "search_openverse"],
        "candidate": {"title": "Amoeba", "source": "wikimedia"},
        "image_b64": "AAAA",
        "mime": "image/png",
        "code": "function Page_core() { return null; }",
        "errors": ["line 1: bad"],
        "error": {"message": "boom", "stack": "at Page_core"},
        "contract": "Declare exactly `function Page_core() { … }`.",
    }


ALL_PROMPTS = [
    DiagnosticPrompt, DiagnosticReviewPrompt, AssessLearnerPrompt, StudyMaterialPrompt, PlanLessonPrompt,
    WritePagePrompt, WriteTestPrompt, PlanInteractivesPrompt, GenerateInteractivePrompt, AlignmentPrompt,
    MediaAgentPrompt, CompilePagePrompt, RepairCodePrompt, RuntimeRepairPrompt,
]  # fmt: skip
LEARNER_FACING = [
    DiagnosticPrompt, StudyMaterialPrompt, PlanLessonPrompt, WritePagePrompt, WriteTestPrompt,
]  # fmt: skip


@pytest.mark.parametrize("prompt", ALL_PROMPTS, ids=lambda p: p.__name__)
def test_builds_a_system_and_a_user_message(prompt):
    messages = prompt().messages(subject())

    assert [type(m) for m in messages] == [SystemMessage, HumanMessage]
    assert messages[0].content.strip() and messages[1].content.strip()


@pytest.mark.parametrize("prompt", ALL_PROMPTS, ids=lambda p: p.__name__)
def test_adds_feedback_about_the_rejected_attempt_once_when_given(prompt):
    messages = prompt().messages(subject(), ["Use exactly 10 questions.", "Fix the ids."])

    user = messages[1].content
    assert user.count("YOUR PREVIOUS ATTEMPT WAS REJECTED") == 1
    assert "- Use exactly 10 questions." in user and "- Fix the ids." in user


@pytest.mark.parametrize("prompt", ALL_PROMPTS, ids=lambda p: p.__name__)
def test_leaves_the_feedback_out_when_there_is_none(prompt):
    for feedback in (None, []):
        assert "REJECTED" not in prompt().messages(subject(), feedback)[1].content


@pytest.mark.parametrize("prompt", LEARNER_FACING, ids=lambda p: p.__name__)
def test_states_the_learners_language(prompt):
    english = prompt().messages(subject())[0].content
    hindi = prompt().messages(subject() | {"profile": {"preferred_language": "hi"}})[0].content
    unknown = prompt().messages(subject() | {"profile": {"preferred_language": "xx"}})[0].content

    assert "Write all learner-facing text in English." in english
    assert "Write all learner-facing text in Hindi." in hindi
    assert "in xx." in unknown


@pytest.mark.parametrize("prompt", [DiagnosticPrompt, AssessLearnerPrompt, PlanLessonPrompt, AlignmentPrompt],
                         ids=lambda p: p.__name__)  # fmt: skip
def test_gives_the_model_the_topic_and_what_the_learner_said(prompt):
    user = prompt().messages(subject())[1].content

    assert 'Topic: "Binary search"' in user
    assert "for my DSA exam" in user


def test_omits_the_learners_remarks_when_there_are_none():
    user = DiagnosticPrompt().messages(subject() | {"user_context": ""})[1].content

    assert "What the learner says" not in user


def test_diagnostic_prompt_states_the_counts_from_the_settings():
    state = subject() | {"settings": {"diagnostic_questions_per_band": 1, "prerequisite_question_count": 3}}

    system = DiagnosticPrompt().messages(state)[0].content

    assert "exactly 5 multiple-choice questions, exactly 1 per band" in system
    assert "the 3 most important concepts" in system
    for band in ("basic", "easy_moderate", "moderate", "moderate_hard", "hard"):
        assert f'"{band}"' in system


def test_review_prompt_includes_the_correct_answers_so_it_can_judge_them():
    user = DiagnosticReviewPrompt().messages(subject())[1].content

    assert '"correct_index"' in user


def test_assessment_prompt_shows_right_and_wrong_but_not_the_answers():
    user = AssessLearnerPrompt().messages(subject())[1].content

    assert "10/10 correct" in user
    assert "[basic] concept basic 0: correct" in user
    assert "correct_index" not in user and "explanation" not in user


def test_assessment_prompt_marks_wrong_answers_and_inconsistent_results():
    wrong_basic = {
        q["id"]: (q["correct_index"] + 1) % 4 if q["band"] == "basic" else q["correct_index"] for q in QUESTIONS
    }
    state = subject() | {"diagnostic_result": GRADER.grade(QUESTIONS, wrong_basic).as_dict()}

    user = AssessLearnerPrompt().messages(state)[1].content

    assert "[basic] concept basic 0: wrong / did not know" in user
    assert "INCONSISTENT (possible guessing)" in user


def test_assessment_prompt_asks_to_copy_the_deterministic_prerequisites():
    state = subject() | {"prerequisites_to_cover": PREREQUISITES[:2]}

    user = AssessLearnerPrompt().messages(state)[1].content

    tail = user.split("prerequisites_to_cover (copy exactly):")[1]
    assert '"Prerequisite 1"' in tail and '"Prerequisite 2"' in tail and '"Prerequisite 3"' not in tail
    assert "Prerequisite quiz" not in user


def test_assessment_prompt_includes_the_prerequisite_quiz_when_there_was_one():
    answers = {q["id"]: q["correct_index"] for q in PREREQUISITE_QUESTIONS[:3]} | {
        q["id"]: (q["correct_index"] + 1) % 4 for q in PREREQUISITE_QUESTIONS[3:]
    }
    state = subject() | {"prerequisite_result": GRADER.grade(PREREQUISITE_QUESTIONS, answers).as_dict()}

    user = AssessLearnerPrompt().messages(state)[1].content

    assert "Prerequisite quiz: 3/5 correct." in user
    assert "[prerequisite] Prerequisite 5: wrong / did not know" in user


@pytest.mark.parametrize(
    ("kind", "phrase"),
    [("cheat_sheet", "CHEAT SHEET"), ("revision_sheet", "REVISION SHEET"), ("practice_sheet", "PRACTICE SHEET")],
)
def test_study_prompt_carries_the_instructions_for_the_chosen_sheet(kind, phrase):
    messages = StudyMaterialPrompt().messages(subject() | {"kind": kind})

    assert phrase in messages[0].content
    assert "Halving the range" in messages[1].content


def test_verify_media_prompt_is_one_multimodal_message_with_the_image():
    messages = VerifyMediaPrompt().messages(subject())

    assert len(messages) == 1 and isinstance(messages[0], HumanMessage)
    text, image = messages[0].content
    assert text["type"] == "text" and "Amoeba" in text["text"]
    assert image == {"type": "image", "base64": "AAAA", "mime_type": "image/png"}


CODE_PROMPTS = [GenerateInteractivePrompt, CompilePagePrompt, RepairCodePrompt, RuntimeRepairPrompt]


@pytest.mark.parametrize("prompt", CODE_PROMPTS, ids=lambda p: p.__name__)
def test_code_prompts_carry_the_sandbox_scope_contract(prompt):
    assert SCOPE_REFERENCE in prompt().messages(subject())[0].content


def test_compile_prompt_lists_what_to_place_and_where():
    user = CompilePagePrompt().messages(subject())[1].content

    assert '<Interactive_widget_core /> after section "s1"' in user
    assert '<Figure asset="asset-1" /> after section "s2"' in user


def test_media_agent_prompt_names_the_tools_and_falls_back_to_the_description_for_the_query():
    state = subject()
    state["spec"] = state["spec"] | {"kind": "image", "media_query": ""}

    messages = MediaAgentPrompt().messages(state)

    assert "search_wikimedia, search_openverse" in messages[0].content
    assert state["spec"]["description"] in messages[1].content.split("Suggested query:")[1]
