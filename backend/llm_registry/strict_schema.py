"""Which of our output schemas a provider can be asked to follow strictly, and the provider-ready form of one.

Strict structured output (Groq's constrained decoding, OpenAI's `strict: true`) needs every field required; Anthropic
refuses recursive schemas and numeric constraints. Each requirement is a small rule class (open for extension: a new
requirement is a new class in a provider's list, not a branch), and `StrictSchema` applies a provider's rules to a
Pydantic model. `problems` is what cannot be sent as the model is written (a test or a pre-flight check reads it);
`prepare` is the JSON schema to send, with what can be fixed fixed (objects closed, numeric constraints dropped: the
lesson's own validators check ranges in code).
"""

from collections.abc import Iterator, Sequence
from typing import Protocol

from pydantic import BaseModel

from .profiles import ProviderKind

NUMERIC_KEYWORDS = ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf")


class SchemaRule(Protocol):
    def check(self, name: str, schema: dict, defs: dict) -> list[str]:
        """The problems of one object schema (named by the model it came from)."""
        ...

    def fix(self, schema: dict) -> None:
        """Change one object schema in place so the problem goes away, where it can be fixed."""
        ...


class AllFieldsRequired:
    """Every property is in `required`: a field the model may leave out is written required and nullable."""

    def check(self, name: str, schema: dict, defs: dict) -> list[str]:
        required = set(schema.get("required", []))
        return [
            f"{name}.{prop} is optional: make it required and nullable"
            for prop in schema.get("properties", {})
            if prop not in required
        ]

    def fix(self, schema: dict) -> None:
        return None  # not fixable here: the field's type decides what "nullable" means


class NoNumericConstraints:
    def check(self, name: str, schema: dict, defs: dict) -> list[str]:
        problems = []
        for prop, sub in schema.get("properties", {}).items():
            found = [k for k in NUMERIC_KEYWORDS if k in sub]
            if found:
                problems.append(
                    f"{name}.{prop} has a numeric constraint ({', '.join(found)}), which this provider does not accept"
                )
        return problems

    def fix(self, schema: dict) -> None:
        for sub in schema.get("properties", {}).values():
            for keyword in NUMERIC_KEYWORDS:
                sub.pop(keyword, None)


class NoRecursion:
    def check(self, name: str, schema: dict, defs: dict) -> list[str]:
        if name in self._reachable(schema, defs):
            return [f"{name} refers to itself, which this provider does not accept"]
        return []

    def fix(self, schema: dict) -> None:
        return None

    def _reachable(self, schema: dict, defs: dict) -> set[str]:
        seen: set[str] = set()
        pending = list(self._refs(schema))
        while pending:
            ref = pending.pop()
            if ref in seen:
                continue
            seen.add(ref)
            pending.extend(self._refs(defs.get(ref, {})))
        return seen

    def _refs(self, node) -> Iterator[str]:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                yield ref.removeprefix("#/$defs/")
            for value in node.values():
                yield from self._refs(value)
        elif isinstance(node, list):
            for value in node:
                yield from self._refs(value)


class StrictSchema:
    def __init__(self, rules: Sequence[SchemaRule] = ()):
        self._rules = tuple(rules)

    def problems(self, model: type[BaseModel]) -> list[str]:
        root = model.model_json_schema()
        defs = root.get("$defs", {})
        found = []
        for name, schema in self._objects(model.__name__, root, defs):
            for rule in self._rules:
                found += rule.check(name, schema, defs)
        return found

    def prepare(self, model: type[BaseModel]) -> dict:
        schema = model.model_json_schema()
        defs = schema.get("$defs", {})
        for _, obj in self._objects(model.__name__, schema, defs):
            obj["additionalProperties"] = False
            for rule in self._rules:
                rule.fix(obj)
        return schema

    @staticmethod
    def _objects(root_name: str, root: dict, defs: dict) -> Iterator[tuple[str, dict]]:
        """The root and every definition that is an object, with the name of the model it came from."""
        if root.get("type") == "object" or "properties" in root:
            yield root_name, root
        for name, schema in defs.items():
            if schema.get("type") == "object" or "properties" in schema:
                yield name, schema


class StrictSchemas:
    """Registry: provider kind -> the rules that provider's strict mode needs. A kind with no entry asks for nothing."""

    RULES: dict[str, tuple[SchemaRule, ...]] = {
        ProviderKind.GROQ: (AllFieldsRequired(),),
        ProviderKind.OPENAI: (AllFieldsRequired(),),
        ProviderKind.ANTHROPIC: (NoNumericConstraints(), NoRecursion()),
    }

    @classmethod
    def for_kind(cls, kind: str) -> StrictSchema:
        return StrictSchema(cls.RULES.get(kind, ()))
