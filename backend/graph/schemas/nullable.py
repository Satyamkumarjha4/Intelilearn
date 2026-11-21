"""Schemas for strict structured output: every field required, the optional ones nullable.

Groq's constrained decoding and OpenAI's `strict: true` accept only a schema whose fields are all required
(`llm_registry/strict_schema.py`), so a field a model may leave out is written `X | None` with no default: on the wire
it is required and nullable. The graph still gets what it always got. A reply that leaves such a field out, or sends
null, is accepted (a provider without strict mode may do either), and the field then holds `NULL_MEANS[name]()`: the
empty list or text the field used to default to, or None.
"""

from collections.abc import Callable, Mapping
from typing import Any, ClassVar

from pydantic import BaseModel, model_validator


def none() -> None:
    return None


class NullableFields(BaseModel):
    #: field name -> a function giving the value to keep when the model sent null or nothing
    NULL_MEANS: ClassVar[Mapping[str, Callable[[], Any]]] = {}

    @model_validator(mode="before")
    @classmethod
    def _a_missing_field_is_null(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return {**{name: None for name in cls.NULL_MEANS}, **data}
        return data

    @model_validator(mode="after")
    def _null_means_the_default(self):
        for name, make in self.NULL_MEANS.items():
            if getattr(self, name) is None:
                setattr(self, name, make())
        return self
