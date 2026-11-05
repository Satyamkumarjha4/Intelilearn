"""The price table, read through a cache, and how an administrator changes it (credits plan T10, T35, K8).

A price is a row of `ActionPrice`. Rows are versioned: changing a price adds a row and switches the old one off, so
history
says what a price was and a reserve (which stores the lines it charged) never depends on the current table. A key
with no
live row is `PriceUnavailable`, never free.
"""

from datetime import datetime

from django.core.cache import cache
from django.db import transaction

from ..models import ActionPrice
from ..refusals import PriceUnavailable
from .values import PriceLine


class PriceBook:
    """The live price of each key. Read on every action, so cached; the cache is cleared whenever a price is saved."""

    CACHE_KEY = "credits:prices"
    TTL_S = 300

    def line(self, key: str) -> PriceLine:
        credits, label = self._row(key)
        return PriceLine(key, label, credits)

    def credits(self, key: str) -> int:
        return self._row(key)[0]

    @classmethod
    def clear(cls) -> None:
        cache.delete(cls.CACHE_KEY)

    def _row(self, key: str) -> tuple[int, str]:
        table = self._table()
        if key not in table:
            raise PriceUnavailable(key)
        return table[key]

    def _table(self) -> dict:
        table = cache.get(self.CACHE_KEY)
        if table is None:
            rows = ActionPrice.objects.filter(active=True).values_list("key", "credits", "label")
            table = {key: (credits, label) for key, credits, label in rows}
            cache.set(self.CACHE_KEY, table, self.TTL_S)
        return table


class PriceCatalog:
    """Changing prices: always by adding a row."""

    def revise(self, key: str, credits: int, *, by: str, now: datetime, label: str | None = None) -> ActionPrice:
        """Make `credits` the live price of `key` (with `label`, or the old label). The old row is switched off and
        kept.
        Nothing changes when the price and label are as they were."""
        if isinstance(credits, bool) or not isinstance(credits, int) or credits < 0:
            raise ValueError(f"{credits!r} is not a price.")
        with transaction.atomic():
            current = ActionPrice.objects.select_for_update().filter(key=key, active=True).first()
            label = label if label is not None else (current.label if current else key)
            if current and current.credits == credits and current.label == label:
                return current
            if current:
                current.active = False
                current.save(update_fields=["active"])
            return ActionPrice.objects.create(
                key=key, credits=credits, label=label, active=True, updated_by=by, updated_at=now
            )

    def deactivate(self, key: str, *, by: str, now: datetime) -> None:
        """Switch the live price of `key` off. The key is then unavailable, not free."""
        with transaction.atomic():
            current = ActionPrice.objects.select_for_update().filter(key=key, active=True).first()
            if current:
                current.active = False
                current.updated_by, current.updated_at = by, now
                current.save(update_fields=["active", "updated_by", "updated_at"])
