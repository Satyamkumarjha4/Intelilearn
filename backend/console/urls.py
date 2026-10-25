from django.urls import path

from .views import overview, people, registry, routing, runs, settings, usage

urlpatterns = [
    path("overview", overview.OverviewView.as_view(), name="console-overview"),
    path("usage", usage.UsageView.as_view(), name="console-usage"),
    path("usage/export.csv", usage.UsageExportView.as_view(), name="console-usage-export"),
    path("runs", runs.RunListView.as_view(), name="console-runs"),
    path("runs/<str:run_id>", runs.RunDetailView.as_view(), name="console-run"),
    path("runs/<str:run_id>/retry", runs.RunRetryView.as_view(), name="console-run-retry"),
    path("runs/<str:run_id>/cancel", runs.RunCancelView.as_view(), name="console-run-cancel"),
    path("providers", registry.ProviderListView.as_view(), name="console-providers"),
    path("providers/<str:key>", registry.ProviderDetailView.as_view(), name="console-provider"),
    path("models", registry.ModelListView.as_view(), name="console-models"),
    path("models/<str:model_id>", registry.ModelDetailView.as_view(), name="console-model"),
    path("models/<str:model_id>/probe", registry.ModelProbeView.as_view(), name="console-model-probe"),
    path("nodes", routing.NodesView.as_view(), name="console-nodes"),
    path("nodes/<str:key>", routing.NodeDetailView.as_view(), name="console-node"),
    path("profiles", routing.ProfilesView.as_view(), name="console-profiles"),
    path("profiles/<str:name>/preview", routing.ProfilePreviewView.as_view(), name="console-profile-preview"),
    path("flow-settings", settings.FlowSettingsView.as_view(), name="console-flow-settings"),
    path("learners", people.LearnerListView.as_view(), name="console-learners"),
    path("audit", people.AuditListView.as_view(), name="console-audit"),
]
