from django.contrib import admin

from .models import Testimonial


@admin.register(Testimonial)
class TestimonialAdmin(admin.ModelAdmin):
    """A fallback; testimonials are managed from the console, which also keeps the change log."""

    list_display = ("name", "context", "position", "is_published", "consent_confirmed", "is_sample")
    list_filter = ("is_published", "consent_confirmed", "is_sample")
    ordering = ("position", "id")
