"""The landing page's testimonials, managed from the console (docs/architecture/design.md, "Landing page").

Every change writes an `AuditEntry` with the state before and after, in the transaction that makes it. The rules about
what may be published (the learner's consent, never a sample) are the model's own, checked here by `full_clean` so the
console says why in words; the database repeats them as a constraint. A sample can be read, ordered and deleted from
the console but never made, flagged or unflagged here: it is a placeholder made by `seed_sample_testimonials`.
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Max
from django.http import Http404
from rest_framework.exceptions import ValidationError

from console.audit import AuditTrail
from marketing.models import Testimonial


class TestimonialDesk:
    __test__ = False  # not a pytest class, whatever its name suggests

    FIELDS = ("name", "context", "quote", "rating", "position", "is_published", "consent_confirmed", "is_sample")

    def __init__(self, trail: AuditTrail):
        self.trail = trail

    def listing(self) -> list[Testimonial]:
        return list(Testimonial.objects.all())

    def create(self, data: dict) -> Testimonial:
        with transaction.atomic():
            top = Testimonial.objects.aggregate(top=Max("position"))["top"] or 0
            row = Testimonial(**data, position=top + 1, is_sample=False)
            self._check(row)
            row.save()
            self.trail.record("testimonial.create", "testimonial", row.pk, after=self.snapshot(row))
        return row

    def update(self, pk: int, data: dict) -> Testimonial:
        with transaction.atomic():
            row = self._locked(pk)
            before = self.snapshot(row)
            for field, value in data.items():
                setattr(row, field, value)
            self._check(row)
            after = self.snapshot(row)
            if before != after:
                row.save()
                self.trail.record("testimonial.update", "testimonial", row.pk, before=before, after=after)
        return row

    def delete(self, pk: int) -> None:
        with transaction.atomic():
            row = self._locked(pk)
            before = self.snapshot(row)
            row.delete()
            self.trail.record("testimonial.delete", "testimonial", pk, before=before)

    def reorder(self, ids: list[int]) -> list[Testimonial]:
        """Put the testimonials in the order of `ids`, which must name every one exactly once."""
        with transaction.atomic():
            rows = list(Testimonial.objects.select_for_update())
            if sorted(ids) != sorted(row.pk for row in rows):
                raise ValidationError({"ids": ["Send every testimonial's id exactly once, in the new order."]})
            before = [row.pk for row in rows]
            if before != ids:
                by_id = {row.pk: row for row in rows}
                for position, pk in enumerate(ids, start=1):
                    row = by_id[pk]
                    row.position = position
                    row.save(update_fields=["position", "updated_at"])
                self.trail.record(
                    "testimonial.reorder", "testimonial", "all", before={"order": before}, after={"order": ids}
                )
        return self.listing()

    # --- helpers ---------------------------------------------------------------------------------------------------

    @staticmethod
    def _locked(pk: int) -> Testimonial:
        row = Testimonial.objects.select_for_update().filter(pk=pk).first()
        if row is None:
            raise Http404
        return row

    @staticmethod
    def _check(row: Testimonial) -> None:
        try:
            row.full_clean()
        except DjangoValidationError as refused:
            raise ValidationError(refused.message_dict) from refused

    @classmethod
    def snapshot(cls, row: Testimonial) -> dict:
        return {field: getattr(row, field) for field in cls.FIELDS}
