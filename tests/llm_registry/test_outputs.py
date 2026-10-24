"""Unit under test: `llm_registry.outputs`, the OutputAdapter per node output mode (structured, tools, text) that
binds the chat model and judges its reply for the gateway.

Why: binding the wrong way silently changes what the model returns, and misjudging a reply either passes a broken
object to the graph or throws away a usable answer.

Use cases:
- structured output binds with include_raw so parse failures come back as data
- a parsed reply is ok; a missing parse is a problem with the parser's message
- the structured repair messages include the bad reply and the problem
- tool nodes bind the tools and return the whole message
- text nodes return the reply's text
- each mode checks the caller passed what it needs (schema, tools)
- the registry finds the adapter for each output mode
"""

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel

from llm_registry.outputs import (
    OUTPUT_ADAPTERS,
    StructuredOutputAdapter,
    TextOutputAdapter,
    ToolsOutputAdapter,
)


class Answer(BaseModel):
    value: int


class Chat:
    def with_structured_output(self, schema, method=None, include_raw=False):
        return ("structured", schema, method, include_raw)

    def bind_tools(self, tools):
        return ("tools", tools)


def test_structured_binds_with_include_raw():
    bound = StructuredOutputAdapter().bind(Chat(), structured_output_method="json_mode", schema=Answer, tools=None)
    assert bound == ("structured", Answer, "json_mode", True)


def test_structured_parsed_reply_is_ok_and_missing_parse_is_a_problem():
    adapter = StructuredOutputAdapter()
    raw = AIMessage(content="{}")

    good = adapter.interpret({"raw": raw, "parsed": Answer(value=1), "parsing_error": None})
    bad = adapter.interpret({"raw": raw, "parsed": None, "parsing_error": ValueError("value: field required")})
    empty = adapter.interpret({"raw": raw, "parsed": None, "parsing_error": None})

    assert good.ok and good.output == Answer(value=1) and good.message is raw
    assert not bad.ok and bad.problem == "value: field required"
    assert empty.problem == "no structured output was returned"


def test_structured_repair_messages_include_the_reply_and_the_problem():
    adapter = StructuredOutputAdapter()
    outcome = adapter.interpret({"raw": AIMessage(content='{"nope": 1}'), "parsed": None, "parsing_error": "bad"})

    messages = adapter.repair_messages([HumanMessage("hi")], outcome)

    assert [m.type for m in messages] == ["human", "ai", "human"]
    assert messages[1].content == '{"nope": 1}' and "bad" in messages[2].content


def test_tool_nodes_bind_tools_and_return_the_whole_message():
    adapter = ToolsOutputAdapter()
    message = AIMessage(content="", tool_calls=[{"name": "search", "args": {"q": "amoeba"}, "id": "1"}])

    assert adapter.bind(Chat(), structured_output_method="", schema=None, tools=["t"]) == ("tools", ["t"])
    assert adapter.interpret(message).output is message
    assert adapter.repair_messages([], adapter.interpret(message)) is None


def test_text_nodes_return_the_text():
    assert TextOutputAdapter().interpret(AIMessage(content="function Page() {}")).output == "function Page() {}"


def test_each_mode_checks_its_inputs():
    with pytest.raises(ValueError, match="pass schema="):
        StructuredOutputAdapter().check_request("learner.assess", None, None)
    with pytest.raises(ValueError, match="pass tools="):
        ToolsOutputAdapter().check_request("media.search", None, [])
    TextOutputAdapter().check_request("page.compile", None, None)  # nothing required


@pytest.mark.parametrize(
    ("mode", "adapter"),
    [("structured", StructuredOutputAdapter), ("tools", ToolsOutputAdapter), ("text", TextOutputAdapter)],
)
def test_registry_finds_the_adapter_for_each_mode(mode, adapter):
    assert isinstance(OUTPUT_ADAPTERS.for_mode(mode), adapter)
