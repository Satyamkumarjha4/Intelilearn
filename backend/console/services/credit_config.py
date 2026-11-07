"""Prices, plans and the credit settings, edited from the console (credits plan §10, D12).

Every change writes an `AuditEntry` with the state before and after, in the transaction that makes it. A price is
changed by adding a row (`PriceCatalog.revise`), so its history stays and a hold already placed never changes; a plan
or the settings change what is *next* bought or earned and never what already was (a purchase stores what it cost, a
period what it grants). Plans and settings are saved through serializers built from the models, so a value is accepted
here exactly when the model's own validators accept it.
"""

from collections import defaultdict

from django.db import transaction
from django.http import Http404
from django.utils import timezone

from console.audit import AuditTrail
from credits.models import ActionPrice, CreditSettings, Plan
from credits.pricing.book import PriceCatalog


class CreditConfig:
    def __init__(self, trail: AuditTrail, catalog: PriceCatalog | None = None):
        self.trail = trail
        self.catalog = catalog or PriceCatalog()

    # --- reading ---------------------------------------------------------------------------------------------------

    def prices(self) -> list[dict]:
        """One row per key: its live price (or none, which makes the key unavailable and never free) and every earlier
        price, newest first."""
        history: dict[str, list[ActionPrice]] = defaultdict(list)
        for row in ActionPrice.objects.order_by("key", "-id"):
            history[row.key].append(row)
        return [self._price_row(rows) for _, rows in sorted(history.items())]

    def price(self, key: str) -> dict:
        rows = list(ActionPrice.objects.filter(key=key).order_by("-id"))
        if not rows:
            raise Http404
        return self._price_row(rows)

    @staticmethod
    def _price_row(rows: list[ActionPrice]) -> dict:
        live = next((row for row in rows if row.active), None)
        shown = live or rows[0]
        return {
            "key": shown.key,
            "label": shown.label,
            "credits": live.credits if live else None,
            "available": live is not None,
            "updated_by": shown.updated_by,
            "updated_at": shown.updated_at,
            "history": [
                {
                    "credits": row.credits, "label": row.label, "active": row.active,
                    "updated_by": row.updated_by, "updated_at": row.updated_at,
                }
                for row in rows
            ],
        }  # fmt: skip

    # --- changing --------------------------------------------------------------------------------------------------

    def revise_price(self, key: str, credits: int, label: str | None = None) -> dict:
        """Make `credits` the live price of `key`. Adds a row, keeps the old one, and is written to the change log; a
        price and label that are as they were change nothing and write nothing."""
        before = self.price(key)  # 404 for a key that has never had a price: a screen does not make up price keys
        with transaction.atomic():
            now = timezone.now()
            row = self.catalog.revise(key, credits, by=self.trail.actor.email, now=now, label=label)
            after = self.price(key)
            if row.updated_at == now:  # a new row was made
                self.trail.record(
                    "credits.price", "action_price", key,
                    before={"credits": before["credits"], "label": before["label"]},
                    after={"credits": after["credits"], "label": after["label"]},
                )  # fmt: skip
        return after

    def plans(self) -> list[Plan]:
        return list(Plan.objects.all())

    def update_plan(self, key: str, serializer_class, data: dict) -> dict:
        plan = Plan.objects.filter(key=key).first()
        if plan is None:
            raise Http404
        return self._update(plan, serializer_class, data, "credits.plan", "plan", key)

    def settings(self) -> CreditSettings:
        return CreditSettings.load()

    def update_settings(self, serializer_class, data: dict) -> dict:
        current = CreditSettings.load()
        return self._update(current, serializer_class, data, "credits.settings", "credit_settings", current.pk)

    def _update(self, instance, serializer_class, data: dict, action: str, target: str, target_id) -> dict:
        before = serializer_class(instance).data
        serializer = serializer_class(instance, data=data, partial=True)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            saved = serializer.save()
            after = serializer_class(saved).data
            if dict(before) != dict(after):
                self.trail.record(action, target, target_id, before=dict(before), after=dict(after))
        return dict(after)
