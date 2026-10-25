from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from console.pagination import ConsoleCursorPagination
from console.serializers import (
    ModelCreateSerializer,
    ModelSerializer,
    ModelUpdateSerializer,
    ProbeSerializer,
    ProviderSerializer,
    ProviderUpdateSerializer,
)
from console.services.probing import ModelProbeService
from console.services.registry import ModelService, ProviderService
from llm_registry.models import LLMModel, Provider

from .base import CONSOLE_TAG, ConsoleListView, ConsoleView

PROVIDER_KEY = OpenApiParameter("key", str, OpenApiParameter.PATH)
MODEL_ID = OpenApiParameter("model_id", int, OpenApiParameter.PATH)


class ProviderListView(ConsoleListView):
    serializer_class = ProviderSerializer

    class Pagination(ConsoleCursorPagination):
        ordering = "key"
        page_size = 50

    pagination_class = Pagination

    def get_queryset(self):
        return ProviderService(self.audit).listing()

    @extend_schema(
        tags=CONSOLE_TAG,
        summary="List providers",
        description=(
            "Each provider with the *name* of the environment variable that holds its API key and whether it "
            "is set on the server (`api_key_set`). A key's value is never returned. `spend_7d` is the cost of the "
            "provider's calls over the 7d range."
        ),
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class ProviderDetailView(ConsoleView):
    @extend_schema(
        tags=CONSOLE_TAG,
        summary="Change a provider",
        description=(
            "Only `rpm_limit` (null for no limit), `base_url` and `enabled` can be changed; anything else is a 400. "
            "The same rules as the Django admin apply (a base URL only for Ollama and OpenAI-compatible providers)."
        ),
        parameters=[PROVIDER_KEY],
        request=ProviderUpdateSerializer,
        responses={200: ProviderSerializer, 404: OpenApiResponse(description="No such provider.")},
    )
    def patch(self, request, key):
        provider = Provider.objects.filter(key=key).first()
        if provider is None:
            raise NotFound()
        changes = ProviderUpdateSerializer(data=request.data, partial=True)
        changes.is_valid(raise_exception=True)
        updated = ProviderService(self.audit).update(provider, changes.validated_data)
        return Response(ProviderSerializer(updated).data)


class ModelLookup:
    def model_of(self, model_id: str) -> LLMModel:
        try:
            return ModelService.listing().get(pk=int(model_id))
        except (ValueError, LLMModel.DoesNotExist):
            raise NotFound() from None


class ModelListView(ConsoleListView):
    serializer_class = ModelSerializer

    class Pagination(ConsoleCursorPagination):
        ordering = "id"
        page_size = 50

    pagination_class = Pagination

    def get_queryset(self):
        return ModelService.listing()

    @extend_schema(
        tags=CONSOLE_TAG,
        summary="List models",
        description="Each model with its capabilities, limits, prices, the steps that use it and its last test.",
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(
        tags=CONSOLE_TAG,
        summary="Add a model",
        description="Validated like the Django admin: unique per provider, parameters the provider accepts.",
        request=ModelCreateSerializer,
        responses={201: ModelSerializer},
    )
    def post(self, request):
        fields = ModelCreateSerializer(data=request.data)
        fields.is_valid(raise_exception=True)
        return Response(ModelSerializer(ModelService(self.audit).create(fields.validated_data)).data, status=201)


class ModelDetailView(ModelLookup, ConsoleView):
    @extend_schema(
        tags=CONSOLE_TAG,
        summary="Change a model",
        description="Any field but the provider. Validated like the Django admin.",
        parameters=[MODEL_ID],
        request=ModelUpdateSerializer,
        responses={200: ModelSerializer, 404: OpenApiResponse(description="No such model.")},
    )
    def patch(self, request, model_id):
        model = self.model_of(model_id)
        changes = ModelUpdateSerializer(model, data=request.data, partial=True)
        changes.is_valid(raise_exception=True)
        return Response(ModelSerializer(ModelService(self.audit).update(model, changes.validated_data)).data)

    @extend_schema(
        tags=CONSOLE_TAG,
        summary="Delete a model",
        description="Refused with a 409 (`model_in_use`, and the `nodes` using it) while a step has the model bound.",
        parameters=[MODEL_ID],
        responses={
            204: None,
            404: OpenApiResponse(description="No such model."),
            409: OpenApiResponse(description="`model_in_use`."),
        },
    )
    def delete(self, request, model_id):
        ModelService(self.audit).delete(self.model_of(model_id))
        return Response(status=204)


class ModelProbeView(ModelLookup, ConsoleView):
    @extend_schema(
        tags=CONSOLE_TAG,
        summary="Test a model",
        description=(
            "The checks of `manage.py probe_models` for one model, run now and within 20 seconds: a plain call, then "
            "one call for each capability the model declares. Makes real calls to the provider. Always a 200: a model "
            "that fails, a missing key and a test that runs out of time are `ok: false`, the reason in `error`. The "
            "result is kept on the model (`last_probe`)."
        ),
        parameters=[MODEL_ID],
        request=None,
        responses={200: ProbeSerializer, 404: OpenApiResponse(description="No such model.")},
    )
    def post(self, request, model_id):
        model = self.model_of(model_id)
        outcome = ModelProbeService().probe(model)
        ModelService(self.audit).record_probe(model, outcome)
        checks = [
            {"capability": c.capability, "ok": c.ok, "latency_s": round(c.latency_ms / 1000, 3), "detail": c.detail}
            for c in outcome.checks
        ]
        return Response(
            ProbeSerializer(
                {"ok": outcome.ok, "latency_s": outcome.latency_s, "error": outcome.error, "checks": checks}
            ).data
        )
