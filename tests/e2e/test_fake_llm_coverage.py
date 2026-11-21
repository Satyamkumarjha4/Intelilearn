"""Unit under test: which graph nodes the fake LLM server (tests/e2e/fake_llm_server.py) can answer.

Why: mock mode (`make audit-up MODE=mock`, `make fake-llm`) walks every screen on the fake, so a node the fake cannot
answer shows up as a lesson that quietly falls back (a picture "shown unchecked", topic suggestions from the
catalogue) and the walk-through never reaches the code behind it. A node added to the graph with no canned answer
must fail here, not in an auditor's run.

Use cases:
- every node in the catalogue is answered one way or another: a canned builder for its schema, the three study sheet
  builders, the media agent's tool loop, or the text path; a new node with none fails this test
- the picture check (`media.verify`) approves with alt text and a caption, through the real gateway and client
- onboarding topic suggestions: a learner's profile gets six topics named for their field of study, which the real
  `GatewayTopicModel` accepts (at least four usable topics)
- translating topics: the same topics come back in the same order, so the page of four stays four
"""

import pytest
from e2e.fake_llm_server import Canned, FakeLLMServer
from support.fake_llm import FakeLLMBinding

from graph.schemas import MATERIAL_SCHEMAS, MediaVerdict
from llm_registry.gateway import Gateway
from llm_registry.node_specs import NODE_SPECS, OutputMode
from llm_registry.resolver import RegistryResolver
from onboarding.domain import SuggestionRequest, Topic
from onboarding.topic_model import GatewayTopicModel

pytestmark = pytest.mark.django_db

# Nodes whose schema is not one builder's name: the fake serves them another way (see the handler's `do_POST`).
SERVED_ANOTHER_WAY = {
    "study.generate": "one builder per sheet in MATERIAL_SCHEMAS",
    "media.search": "the media agent's tool loop (`_agent_reply`)",
}


@pytest.fixture
def server():
    with FakeLLMServer() as running:
        yield running


class TestEveryNodeIsAnswered:
    @pytest.mark.parametrize("key", list(NODE_SPECS))
    def test_the_node_has_a_canned_answer(self, key):
        spec = NODE_SPECS[key]

        if spec.output is OutputMode.TEXT:
            assert hasattr(Canned, "for_text"), f"{key}: the fake has no text path"
        elif key in SERVED_ANOTHER_WAY:
            assert SERVED_ANOTHER_WAY[key]
        else:
            assert hasattr(Canned, f"build_{spec.schema_name}"), f"{key}: no canned builder for {spec.schema_name}"

    def test_every_study_sheet_has_a_builder(self):
        for schema in MATERIAL_SCHEMAS.values():
            assert hasattr(Canned, f"build_{schema.__name__}")

    def test_the_exceptions_are_real_nodes(self):
        assert set(SERVED_ANOTHER_WAY) <= set(NODE_SPECS)


class TestPictureCheck:
    def test_it_approves_with_alt_text_and_a_caption(self, server, monkeypatch):
        snapshot = FakeLLMBinding.bind(server, monkeypatch, vision=True)

        result = Gateway().invoke("media.verify", [], snapshot=snapshot, schema=MediaVerdict)

        assert result.output.approved is True
        assert result.output.alt_text and result.output.caption


class TestTopicSuggestions:
    def model(self, server, monkeypatch) -> GatewayTopicModel:
        FakeLLMBinding.bind(server, monkeypatch)
        return GatewayTopicModel(gateway=Gateway(sleep=lambda seconds: None), snapshots=RegistryResolver())

    def test_a_profile_gets_six_topics_named_for_their_field_of_study(self, server, monkeypatch):
        request = SuggestionRequest("college", "exam_prep", field_of_study="Botany")

        topics = self.model(server, monkeypatch).suggest(request)

        assert len(topics) == 6 and all("Botany" in topic.title for topic in topics)

    def test_translating_keeps_the_same_topics_in_the_same_order(self, server, monkeypatch):
        topics = [Topic(f"Topic {n}", f"Topic {n}", "Maths", "Because.") for n in range(1, 5)]

        translated = self.model(server, monkeypatch).translate("hi", topics)

        assert [t.title_en for t in translated] == [t.title_en for t in topics]
        assert len(translated) == 4
