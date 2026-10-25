from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from console.serializers import (
    NodeRoutingInputSerializer,
    NodeRoutingSerializer,
    ProfilePreviewSerializer,
    RoutingProfileSerializer,
    RoutingSerializer,
)
from console.services.routing import (
    NodeRoutingPresenter,
    NodeRoutingReader,
    NodeRoutingValidator,
    NodeRoutingWriter,
    ProfilePreview,
    ProposedBinding,
    ProposedNode,
)
from llm_registry.models import LLMModel
from llm_registry.node_specs import Stage

from .base import CONSOLE_TAG, ConsoleView

NODE_KEY = OpenApiParameter("key", str, OpenApiParameter.PATH, description="A step, e.g. lesson.plan.")
PROFILE_NAME = OpenApiParameter("name", str, OpenApiParameter.PATH, description="default, cheap, balanced or quality.")


class NodesView(ConsoleView):
    @extend_schema(
        tags=CONSOLE_TAG,
        summary="Routing of every step",
        description=(
            "Every step of the lesson graph grouped by phase (in the order of a lesson): what it does, whether it is "
            "optional, what a model needs to serve it, its settings, and its models in priority order. A binding's "
            "`problems` say why that model cannot serve the step."
        ),
        responses={200: RoutingSerializer},
    )
    def get(self, request):
        presenter = NodeRoutingPresenter()
        nodes = NodeRoutingReader().nodes()
        phases = [
            {"phase": stage.value, "nodes": [presenter.present(n) for n in nodes if n.spec.stage == stage]}
            for stage in Stage
        ]
        return Response(RoutingSerializer({"phases": [phase for phase in phases if phase["nodes"]]}).data)


class NodeDetailView(ConsoleView):
    @extend_schema(
        tags=CONSOLE_TAG,
        summary="Save the routing of a step",
        description=(
            "Replaces the step's settings and its whole chain, atomically: either all of it is saved or none. The "
            "order of `bindings` is the priority. Refused (400, with the problems under `fields.bindings`) when a "
            "required step is switched off, an enabled step has no enabled model, a model does not exist or is "
            "switched off, its provider's API key is not set, or it cannot serve the step (capabilities, output size, "
            "context, parameters)."
        ),
        parameters=[NODE_KEY],
        request=NodeRoutingInputSerializer,
        responses={200: NodeRoutingSerializer, 404: OpenApiResponse(description="No such step.")},
    )
    def put(self, request, key):
        node = NodeRoutingReader().get(key)
        if node is None:
            raise NotFound()
        data = NodeRoutingInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        proposed = self._proposed(data.validated_data)
        if problems := NodeRoutingValidator().problems(node, proposed):
            raise ValidationError(problems)
        saved = NodeRoutingWriter(self.audit).replace(node, proposed)
        return Response(NodeRoutingSerializer(NodeRoutingPresenter().present(saved)).data)

    @staticmethod
    def _proposed(data: dict) -> ProposedNode:
        models = LLMModel.objects.select_related("provider").in_bulk([b["model"] for b in data["bindings"]])
        bindings = tuple(
            ProposedBinding(
                model=models.get(b["model"]),
                label=str(models[b["model"]]) if b["model"] in models else f"model {b['model']}",
                max_retries=b["max_retries"],
                enabled=b["enabled"],
                params=b["overrides"].get("params", {}),
                reasoning_effort=b["overrides"].get("reasoning_effort", ""),
            )
            for b in data["bindings"]
        )
        return ProposedNode(
            enabled=data["enabled"],
            reasoning_effort=data["reasoning_effort"],
            max_attempts=data["max_attempts"],
            max_tool_steps=data["max_tool_steps"],
            timeout_s=data["timeout_s"],
            params_override=data["params_override"],
            bindings=bindings,
        )


class ProfilesView(ConsoleView):
    @extend_schema(
        tags=CONSOLE_TAG,
        summary="Routing profiles",
        description="The seed profiles (`manage.py seed_registry --profile`): default, cheap, balanced and quality.",
        responses={200: RoutingProfileSerializer(many=True)},
    )
    def get(self, request):
        return Response(RoutingProfileSerializer(ProfilePreview().listing(), many=True).data)


class ProfilePreviewView(ConsoleView):
    @extend_schema(
        tags=CONSOLE_TAG,
        summary="Preview a profile",
        description=(
            "What loading the profile would do to every step, without saving anything: the step as it is and as it "
            "would be, whether it changes, and the problems that would stop it being saved (a model the registry "
            "lacks, a provider without a key). A step's `proposed` has the shape of a `PUT /nodes/{key}` body."
        ),
        parameters=[PROFILE_NAME],
        request=None,
        responses={200: ProfilePreviewSerializer, 404: OpenApiResponse(description="No such profile.")},
    )
    def post(self, request, name):
        preview = ProfilePreview().preview(name)
        if preview is None:
            raise NotFound()
        return Response(ProfilePreviewSerializer(preview).data)
