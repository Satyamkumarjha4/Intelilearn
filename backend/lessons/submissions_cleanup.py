"""The data step before a lesson was limited to one test submission: keep one per lesson, delete the rest.

It works on whichever `TestSubmission` model it is given, so a migration can pass the historical one. The learner's
graded result is the one worth keeping; failing that, the latest go.
"""

from django.db.models import Count


class SubmissionDeduplicator:
    GRADED = "graded"

    def plan(self, model) -> int:
        """How many rows `run` would delete."""
        return len(self._doomed(model))

    def run(self, model) -> int:
        """Delete every submission but one per lesson. → how many were deleted."""
        doomed = self._doomed(model)
        model.objects.filter(pk__in=doomed).delete()
        return len(doomed)

    def _doomed(self, model) -> list:
        crowded = model.objects.values("lesson_id").annotate(n=Count("pk")).filter(n__gt=1).values("lesson_id")
        doomed = []
        for lesson_id in [row["lesson_id"] for row in crowded]:
            rows = list(model.objects.filter(lesson_id=lesson_id).order_by("-submitted_at"))
            graded = [row for row in rows if row.status == self.GRADED]
            keep = (graded or rows)[0]
            doomed += [row.pk for row in rows if row.pk != keep.pk]
        return doomed
