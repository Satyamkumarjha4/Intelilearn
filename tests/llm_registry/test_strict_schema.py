"""Unit under test: `llm_registry.strict_schema` (`StrictSchema` and the rule classes of each provider): which of our
output schemas a provider can be asked to follow strictly, and the provider-ready form of one.

Why: Groq's strict structured output ("never errors or produces invalid JSON") needs every field required, and the
live log shows the cost of not asking for it: `learner.assess` was invalid in 9 of 14 attempts in best-effort mode.
OpenAI is the same; Anthropic refuses recursion and numeric constraints. A schema that cannot be sent strictly must be
found by a test, not by a 400 in production, and a field a model may leave out must be written as required and
nullable.

Use cases:
- a schema whose fields are all required has no problems
- a field with a default is reported with the schema and field it belongs to, nested ones too
- a recursive schema is reported (Anthropic refuses it)
- numeric constraints are reported for Anthropic only, and `prepare` strips them (the lesson's own validators check
  the range in code)
- `prepare` closes every object (`additionalProperties: false`) without changing the model
- the provider's rule set is chosen by provider kind; Gemini and unknown kinds ask for nothing
- every output schema a node asks a model for can be sent strictly to Groq and OpenAI
"""

from pydantic import BaseModel, Field

from llm_registry.profiles import ProviderKind
from llm_registry.strict_schema import StrictSchemas


class Inner(BaseModel):
    name: str
    note: str | None  # required and nullable: fine


class Outer(BaseModel):
    title: str
    items: list[Inner]
    index: int = Field(ge=0, le=3, description="0 to 3")


class Loose(BaseModel):
    inner: Inner
    query: str = Field(default="", description="optional")


class Node(BaseModel):
    value: int
    children: list["Node"]


GROQ = StrictSchemas.for_kind(ProviderKind.GROQ)
ANTHROPIC = StrictSchemas.for_kind(ProviderKind.ANTHROPIC)


def test_a_schema_whose_fields_are_all_required_has_no_problems():
    assert GROQ.problems(Outer) == []


def test_a_field_with_a_default_is_reported_with_where_it_is():
    assert GROQ.problems(Loose) == ["Loose.query is optional: make it required and nullable"]


def test_a_recursive_schema_is_reported_for_anthropic():
    assert ANTHROPIC.problems(Node) == ["Node refers to itself, which this provider does not accept"]
    assert GROQ.problems(Node) == []


def test_numeric_constraints_are_reported_for_anthropic_only_and_stripped_by_prepare():
    assert ANTHROPIC.problems(Outer) == ["Outer.index has a numeric constraint (minimum, maximum), which this provider "
                                         "does not accept"]  # fmt: skip
    assert GROQ.problems(Outer) == []

    prepared = ANTHROPIC.prepare(Outer)

    assert "minimum" not in prepared["properties"]["index"] and "maximum" not in prepared["properties"]["index"]


def test_prepare_closes_every_object_and_leaves_the_model_alone():
    prepared = GROQ.prepare(Outer)

    assert prepared["additionalProperties"] is False
    assert prepared["$defs"]["Inner"]["additionalProperties"] is False
    assert Outer.model_json_schema().get("additionalProperties") is None


def test_the_rule_set_is_chosen_by_provider_kind():
    assert StrictSchemas.for_kind(ProviderKind.OPENAI).problems(Loose) == GROQ.problems(Loose)
    assert StrictSchemas.for_kind(ProviderKind.GOOGLE_GENAI).problems(Loose) == []
    assert StrictSchemas.for_kind("something-else").problems(Loose) == []


def test_every_output_schema_of_the_lesson_graph_can_be_sent_strictly_to_groq_and_openai():
    from graph import schemas
    from llm_registry.node_specs import NODE_SPECS
    from onboarding.schemas import TopicSuggestions
    from quizzes.traits import TopicTraitsJudgement

    elsewhere = {"TopicSuggestions": TopicSuggestions, "TopicTraitsJudgement": TopicTraitsJudgement}
    names = {n.strip() for spec in NODE_SPECS.values() for n in spec.schema_name.split("|") if n.strip()}
    models = [elsewhere.get(name) or getattr(schemas, name) for name in sorted(names)]
    assert len(models) >= 10

    problems = {m.__name__: GROQ.problems(m) for m in models if GROQ.problems(m)}

    assert problems == {}
