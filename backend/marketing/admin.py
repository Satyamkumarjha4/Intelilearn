from django.contrib import admin

from .models import DemoQuestion


@admin.register(DemoQuestion)
class DemoQuestionAdmin(admin.ModelAdmin):
    list_display = ("question", "subject", "level_label", "band", "is_active", "created_at")
    list_filter = ("subject", "band", "is_active")
    list_editable = ("is_active",)
    search_fields = ("question", "subject")
    ordering = ("id",)
