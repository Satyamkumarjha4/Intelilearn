"""Unit under test: `graph.schemas.nullable.NullableFields` and the schemas that use it (the lesson sections, the test
question, the cheat and revision sheets, the alignment report, the interactive spec).

Why: strict structured output (Groq, OpenAI) needs every field required, so a field a model may leave out is required
and nullable on the wire. The graph must still see what it always saw: an empty list or an empty text where a field used
to default, and a model without strict mode may still omit the field altogether.

Use cases:
- on the wire every field of these schemas is required, and the ones that were optional also accept null
- a reply that leaves a field out, or sends null, gets the field's old default (an empty list, an empty text, or None)
- a value the model did send is kept
- the stored form (`model_dump`) is the one the graph always had: no None where a list or text used to be
- a test question keeps its per-type fields as None, and its own type check still runs
- the alignment verdict still works with no issues sent
"""

import pytest

from graph.schemas import AlignmentReport, InteractiveSpec, PageContent, RevisionSheet
from graph.schemas.lesson import Section
from graph.schemas.lesson import TestQuestion as Question
from graph.schemas.study import CheatItem
from llm_registry.profiles import ProviderKind
from llm_registry.strict_schema import StrictSchemas

SCORES = dict(topic_relevance=4, level_fit=4, prerequisite_coverage=4, factual_accuracy=4, interactive_relevance=4)


def test_on_the_wire_every_field_is_required_and_the_optional_ones_accept_null():
    schema = Section.model_json_schema()

    assert set(schema["properties"]) == set(schema["required"])
    assert {"type": "null"} in schema["properties"]["key_points"]["anyOf"]
    assert StrictSchemas.for_kind(ProviderKind.GROQ).problems(PageContent) == []


@pytest.mark.parametrize("reply", [{}, {"key_points": None}])
def test_a_field_left_out_or_null_gets_its_old_default(reply):
    section = Section.model_validate({"id": "s1", "heading": "h", "body": "b", **reply})

    assert section.key_points == [] and section.concepts == [] and section.callouts == []


def test_a_value_the_model_sent_is_kept():
    section = Section.model_validate({"id": "s1", "heading": "h", "body": "b", "key_points": ["one"]})

    assert section.key_points == ["one"]


def test_the_stored_form_is_the_one_the_graph_always_had():
    item = CheatItem.model_validate({"label": "l", "kind": "term", "content": "c"})

    assert item.model_dump() == {"label": "l", "kind": "term", "content": "c", "formula": "", "variables": [],
                                 "when_to_use": ""}  # fmt: skip


def test_the_revision_sheet_and_the_interactive_spec_keep_their_defaults_too():
    sheet = RevisionSheet.model_validate({"title": "t", "overview": "o", "subtopics": [
        {"title": "s", "summary": "x", "key_points": ["k"]}]})  # fmt: skip
    spec = InteractiveSpec.model_validate({"id": "a", "page": "core", "anchor_section": "s1", "kind": "svg_diagram",
                                           "purpose": "p", "description": "d"})  # fmt: skip

    assert sheet.final_tips == [] and sheet.subtopics[0].common_mistakes == []
    assert spec.media_query == ""


def test_a_test_question_keeps_its_per_type_fields_as_none_and_still_checks_its_type():
    mcq = Question.model_validate({
        "id": "t1", "type": "mcq", "concept": "c", "difficulty": "easy", "question": "q",
        "options": ["a", "b", "c", "d"], "correct_index": 1,
    })  # fmt: skip

    assert mcq.correct_indices is None and mcq.answer_expr is None and mcq.model_answer is None
    with pytest.raises(ValueError, match="needs"):
        Question.model_validate({"id": "t1", "type": "mcq", "concept": "c", "difficulty": "easy", "question": "q"})


def test_the_alignment_verdict_works_when_no_issues_are_sent():
    report = AlignmentReport.model_validate({**SCORES, "passed": True})

    assert report.issues == [] and report.recompute_passed(3) is True
