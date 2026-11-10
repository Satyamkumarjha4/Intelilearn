from django.contrib import admin

from .models import DemoQuestion, Testimonial


@admin.register(DemoQuestion)
class DemoQuestionAdmin(admin.ModelAdmin):
    list_display = ("question", "subject", "level_label", "band", "is_active", "created_at")
    list_filter = ("subject", "band", "is_active")
    list_editable = ("is_active",)
    search_fields = ("question", "subject")
    ordering = ("id",)


@admin.register(Testimonial)
class TestimonialAdmin(admin.ModelAdmin):
    """A fallback; testimonials are managed from the console, which also keeps the change log."""

    list_display = ("name", "context", "position", "is_published", "consent_confirmed", "is_sample")
    list_filter = ("is_published", "consent_confirmed", "is_sample")
    ordering = ("position", "id")
