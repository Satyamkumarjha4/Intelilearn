"""The change log: `AuditTrail.record` writes the `AuditEntry` of a change (see console/models.py)."""

import json

from django.core.serializers.json import DjangoJSONEncoder

from .models import AuditEntry


class AuditTrail:
    """Records changes made by one staff member. Services call `record` inside the transaction that makes the change,
    so a change and its entry are saved together or not at all."""

    def __init__(self, actor):
        self.actor = actor

    def record(self, action: str, target_type: str, target_id, *, before=None, after=None) -> AuditEntry:
        return AuditEntry.objects.create(
            actor=self.actor,
            actor_email=self.actor.email,
            action=action,
            target_type=target_type,
            target_id=str(target_id),
            before=self._plain(before),
            after=self._plain(after),
        )

    @staticmethod
    def _plain(snapshot):
        """JSON as stored: decimals, dates and ids become strings the way the API shows them."""
        return None if snapshot is None else json.loads(json.dumps(snapshot, cls=DjangoJSONEncoder))
