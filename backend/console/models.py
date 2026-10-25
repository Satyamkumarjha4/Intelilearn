"""The console's change log: one immutable row for every change a staff member makes through it."""

from django.conf import settings
from django.db import models


class AuditEntry(models.Model):
    """Who changed what, with the target as it was and as it became. Written by `console.audit.AuditTrail` in the same
    transaction as the change, never edited afterwards. Snapshots hold what the console API returns, which carries no
    secret (a provider is its key's variable *name*, never the key)."""

    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    # The address at the time, so the trail still says who it was after the account is deleted.
    actor_email = models.EmailField(blank=True)
    action = models.CharField(max_length=60, help_text="What was done, e.g. model.update or run.retry.")
    target_type = models.CharField(max_length=40, help_text="provider, model, node, flow_settings or run.")
    target_id = models.CharField(max_length=80, help_text="The provider key, node key, row id or run id.")
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name_plural = "audit entries"
        indexes = [models.Index(fields=["target_type", "target_id"], name="audit_target_idx")]

    def __str__(self):
        return f"{self.actor_email or 'someone'}: {self.action} {self.target_type} {self.target_id}"
