from django.contrib import admin

from .models import AuditEntry


@admin.register(AuditEntry)
class AuditEntryAdmin(admin.ModelAdmin):
    """The change log, read-only: an entry that could be edited would prove nothing."""

    list_display = ["created_at", "actor_email", "action", "target_type", "target_id"]
    list_filter = ["action", "target_type"]
    search_fields = ["actor_email", "target_id"]
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
