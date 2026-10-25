from django.contrib import admin
from django.utils.html import format_html

from .models import (
    FlowSettings,
    GraphRun,
    Lesson,
    LessonVersion,
    MediaAsset,
    Quiz,
    QuizAttempt,
    StudyMaterial,
    TestSubmission,
)


class RunInline(admin.TabularInline):
    model = GraphRun
    extra = 0
    can_delete = False
    fields = ["graph", "trigger", "status", "error", "created_at", "finished_at"]
    readonly_fields = fields
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ["topic", "owner", "stage", "route", "level", "created_at", "problem"]
    list_filter = ["stage", "route", "level"]
    search_fields = ["topic", "owner__email"]
    date_hierarchy = "created_at"
    inlines = [RunInline]
    readonly_fields = ["id", "created_at", "updated_at", "config_snapshot", "settings_snapshot"]

    @admin.display(description="Error")
    def problem(self, obj):
        return format_html("<span title='{}'>{}</span>", obj.error, obj.error[:60]) if obj.error else ""


@admin.register(GraphRun)
class GraphRunAdmin(admin.ModelAdmin):
    list_display = ["lesson", "graph", "trigger", "status", "created_at", "started_at", "finished_at"]
    list_filter = ["graph", "trigger", "status"]
    search_fields = ["lesson__topic", "lesson__owner__email"]
    readonly_fields = ["id", "created_at", "started_at", "finished_at", "node_status", "celery_task_id", "payload"]


@admin.register(Quiz)
class QuizAdmin(admin.ModelAdmin):
    list_display = ["lesson", "kind", "created_at"]
    list_filter = ["kind"]
    search_fields = ["lesson__topic"]


@admin.register(QuizAttempt)
class QuizAttemptAdmin(admin.ModelAdmin):
    list_display = ["quiz", "score", "submitted_at"]

    @admin.display(description="Score")
    def score(self, obj):
        return f"{obj.result.get('correct')}/{obj.result.get('total')}"


@admin.register(StudyMaterial)
class StudyMaterialAdmin(admin.ModelAdmin):
    list_display = ["lesson", "kind", "created_at"]
    list_filter = ["kind"]


@admin.register(MediaAsset)
class MediaAssetAdmin(admin.ModelAdmin):
    list_display = ["lesson", "spec_id", "kind", "source", "license", "verified"]
    list_filter = ["kind", "source", "verified"]


@admin.register(TestSubmission)
class TestSubmissionAdmin(admin.ModelAdmin):
    list_display = ["lesson", "status", "score", "submitted_at", "graded_at"]
    list_filter = ["status"]
    search_fields = ["lesson__topic", "lesson__owner__email"]
    readonly_fields = ["id", "submitted_at", "graded_at", "answers", "result", "error"]

    @admin.display(description="Score")
    def score(self, obj):
        card = (obj.result or {}).get("score")
        return f"{card['awarded']}/{card['available']}" if card else ""


@admin.register(LessonVersion)
class LessonVersionAdmin(admin.ModelAdmin):
    list_display = ["lesson", "code_version", "reason", "created_at"]


@admin.register(FlowSettings)
class FlowSettingsAdmin(admin.ModelAdmin):
    """One row of settings that every new lesson snapshots. There is nothing to add or delete."""

    def has_add_permission(self, request):
        return not FlowSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
