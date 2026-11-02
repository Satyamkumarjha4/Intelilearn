"""Moving every lesson's test from `Lesson.final_test` onto the record of questions (migration 0019).

A lesson's "first set" is the questions it was built with, which attempt 1 serves. They used to be a JSON column; now
each is a `Question` row with a place (`first_set_position`). This works on the models of the migration it is run from
(`apps`), as `StoredRenames` does, so it does not depend on later code.
"""

from graph.questions.dedupe import StemHash


class FirstSetBackfill:
    TITLE = "Test your understanding"

    def forward(self, apps, using: str = "default") -> None:
        """Every lesson that has a test gets its questions as the first set. A lesson nobody has attempted can serve
        them, so their rows are no longer withdrawn; a lesson that has attempts keeps its rows withdrawn (they only feed
        the exclusion list) and its attempts, which hold their own copy, are not touched."""
        Lesson, Question, Submission = (
            apps.get_model("lessons", name) for name in ("Lesson", "Question", "TestSubmission")
        )
        for lesson in Lesson.objects.using(using).exclude(final_test__isnull=True).iterator():
            questions = (lesson.final_test or {}).get("questions") or []
            if not questions:
                continue
            attempted = Submission.objects.using(using).filter(lesson_id=lesson.pk).exists()
            Question.objects.using(using).filter(lesson_id=lesson.pk, first_set_position__isnull=False).update(
                first_set_position=None
            )
            placed: set = set()
            for old in questions:
                row = self._row(Question.objects.using(using), lesson, old, attempted)
                if row.pk in placed:
                    continue  # the same stem twice is one row, in the place of the first
                placed.add(row.pk)
                update = {"first_set_position": len(placed) - 1}
                if not attempted:
                    update["retired"] = False
                Question.objects.using(using).filter(pk=row.pk).update(**update)

    def backward(self, apps, using: str = "default") -> None:
        """Writes `final_test` back for every lesson that has a first set and no test column value."""
        Lesson, Question = apps.get_model("lessons", "Lesson"), apps.get_model("lessons", "Question")
        lesson_ids = (
            Question.objects.using(using)
            .filter(first_set_position__isnull=False)
            .values_list("lesson_id", flat=True)
            .distinct()
        )
        for lesson in Lesson.objects.using(using).filter(pk__in=lesson_ids, final_test__isnull=True).iterator():
            rows = (
                Question.objects.using(using)
                .filter(lesson_id=lesson.pk, first_set_position__isnull=False)
                .order_by("first_set_position")
            )
            questions = [{**row.payload, "question_id": str(row.pk)} for row in rows]
            Lesson.objects.using(using).filter(pk=lesson.pk).update(
                final_test={"title": self.TITLE, "questions": questions}
            )

    @staticmethod
    def _row(rows, lesson, old: dict, attempted: bool):
        """The row of an old question: by the id it carries, else by its stem, else a new one. `rows` is the question
        manager of the database being migrated."""
        if old.get("question_id"):
            found = rows.filter(lesson_id=lesson.pk, pk=old["question_id"]).first()
            if found:
                return found
        stem_hash = StemHash.of(old.get("question", ""))
        found = rows.filter(lesson_id=lesson.pk, stem_hash=stem_hash).first()
        if found:
            return found
        payload = {key: value for key, value in old.items() if key != "question_id"}
        return rows.create(
            lesson_id=lesson.pk,
            type=old.get("type", ""),
            difficulty=old.get("difficulty", ""),
            concept=str(old.get("concept", ""))[:200],
            marks=old.get("marks") or 0,
            payload=payload,
            stem_hash=stem_hash,
            batch=None,
            retired=attempted,
        )
