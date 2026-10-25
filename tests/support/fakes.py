"""Test doubles for the ports the graph depends on (see docs/testing.md §4).

- `FakeGateway`: scripted outputs per node key; records every call. An item may be a Pydantic object, a dict (validated
  against the call's schema), a callable taking the messages, or an exception to raise.
- `FakeSandbox`: a `CodeSandbox` whose LaTeX/code checks return what the test configured.
- `ListEvents`: an `EventSink` that keeps what was emitted.
"""

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any


@dataclass
class GatewayCall:
    node_key: str
    messages: list
    schema: Any
    tools: Any
    snapshot: dict
    lesson_id: Any
    run_id: Any


class FakeGateway:
    def __init__(self, scripts: dict[str, list] | None = None):
        self.scripts = {key: list(items) for key, items in (scripts or {}).items()}
        self.responders: dict[str, Any] = {}
        self.calls: list[GatewayCall] = []

    def respond(self, node_key: str, responder) -> "FakeGateway":
        """Answer every call to `node_key` with `responder(messages)` (for nodes that run in parallel, where the order
        of calls is not fixed). Scripted items for the same key are used first."""
        self.responders[node_key] = responder
        return self

    def script(self, node_key: str, *items) -> "FakeGateway":
        self.scripts.setdefault(node_key, []).extend(items)
        return self

    def called(self, node_key: str) -> list[GatewayCall]:
        return [call for call in self.calls if call.node_key == node_key]

    def invoke(self, node_key, messages, *, snapshot, schema=None, tools=None, lesson_id=None, run_id=None,
               on_event=None):  # fmt: skip
        self.calls.append(GatewayCall(node_key, list(messages), schema, tools, snapshot, lesson_id, run_id))
        queue = self.scripts.get(node_key)
        if queue:
            item = queue.pop(0)
        elif node_key in self.responders:
            item = self.responders[node_key]
        else:
            raise AssertionError(f"FakeGateway has no scripted output left for {node_key}")
        if isinstance(item, Exception):
            raise item
        if callable(item):
            item = item(messages)
        if isinstance(item, dict) and schema is not None:
            item = schema.model_validate(item)
        return SimpleNamespace(output=item, message=None, model=None, fallback_index=0, attempts=1)


@dataclass
class FakeSandbox:
    latex_errors: list[str] = field(default_factory=list)
    code_errors: list[str] = field(default_factory=list)
    failing_components: set[str] = field(default_factory=set)  # required names whose check always fails
    latex_calls: list[list[str]] = field(default_factory=list)

    def latex(self, expressions):
        self.latex_calls.append(list(expressions))
        return list(self.latex_errors)

    def check_code(self, code, *, required=(), components=(), asset_ids=()):
        errors = list(self.code_errors)
        if self.failing_components & set(required):
            errors.append("line 1:0 [forbidden-global] `fetch` is not allowed in lesson code")
        return SimpleNamespace(ok=not errors, errors=errors)

    def render_check(self, code, data, *, pages, media_files):
        raise NotImplementedError


class ListEvents:
    def __init__(self):
        self.events: list[dict] = []

    def __call__(self, event: dict) -> None:
        self.events.append(event)

    def of_type(self, kind: str) -> list[dict]:
        return [e for e in self.events if e["type"] == kind]
