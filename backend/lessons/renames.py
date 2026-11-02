"""The data migration behind the level and difficulty renames of the modular lessons (migration 0006).

Levels were novice, beginner, intermediate, advanced and are now beginner, foundation, proficient, expert. Difficulties
were easy, medium, hard and are now easy, basic, standard, difficult, expert. Stored lessons carry both in several
JSON columns, so the rename walks the documents instead of naming every place by hand, and `StoredRenames.COLUMNS`
lists the columns it covers: a test fails when a model gains a JSON column that is in neither list.

Documents rewritten to the new level names get `level_scheme: 2` (graph/levels.py `LevelScheme`). Graph checkpoints are
not rewritten; they have no marker, so the code reads them as legacy.

Going back is lossy for the two difficulties the old scheme did not have: basic reads as easy and expert as hard.
"""

from typing import Any, ClassVar

LEVEL_SCHEME_KEY = "level_scheme"
LEVEL_SCHEME = 2  # written here, not imported: a migration describes the data as it was when it ran


class LevelRename:
    FORWARD: ClassVar[dict[str, str]] = {
        "novice": "beginner", "beginner": "foundation", "intermediate": "proficient", "advanced": "expert",
    }  # fmt: skip
    BACKWARD: ClassVar[dict[str, str]] = {new: old for old, new in FORWARD.items()}

    def forward_name(self, name: str) -> str:
        return self.FORWARD.get(name, name)

    def backward_name(self, name: str) -> str:
        return self.BACKWARD.get(name, name)

    def forward_document(self, document: dict | None) -> dict | None:
        """An assessment or plan under the old names, rewritten and stamped. Stamped and empty ones are as they were."""
        if not document or document.get(LEVEL_SCHEME_KEY) == LEVEL_SCHEME:
            return document
        return {**document, "level": self.forward_name(document.get("level", "")), LEVEL_SCHEME_KEY: LEVEL_SCHEME}

    def backward_document(self, document: dict | None) -> dict | None:
        if not document or document.get(LEVEL_SCHEME_KEY) != LEVEL_SCHEME:
            return document
        rest = {k: v for k, v in document.items() if k != LEVEL_SCHEME_KEY}
        return {**rest, "level": self.backward_name(document.get("level", ""))}


class DifficultyRename:
    FORWARD: ClassVar[dict[str, str]] = {"medium": "standard", "hard": "difficult"}
    BACKWARD: ClassVar[dict[str, str]] = {"basic": "easy", "standard": "medium", "difficult": "hard", "expert": "hard"}
    NEW_MIX: ClassVar[tuple[str, ...]] = ("easy", "basic", "standard", "difficult", "expert")
    OLD_MIX: ClassVar[tuple[str, ...]] = ("easy", "medium", "hard")

    def forward(self, node: Any) -> Any:
        return self._walk(node, self.FORWARD, self.NEW_MIX)

    def backward(self, node: Any) -> Any:
        return self._walk(node, self.BACKWARD, self.OLD_MIX)

    def _walk(self, node: Any, names: dict[str, str], mix_keys: tuple[str, ...]) -> Any:
        """A copy of the document with every `difficulty` value renamed and every `difficulty_mix` re-keyed."""
        if isinstance(node, list):
            return [self._walk(item, names, mix_keys) for item in node]
        if not isinstance(node, dict):
            return node
        out = {}
        for key, value in node.items():
            if key == "difficulty" and isinstance(value, str):
                out[key] = names.get(value, value)
            elif key == "difficulty_mix" and isinstance(value, dict):
                out[key] = self._mix(value, names, mix_keys)
            else:
                out[key] = self._walk(value, names, mix_keys)
        return out

    @staticmethod
    def _mix(mix: dict, names: dict[str, str], keys: tuple[str, ...]) -> dict:
        counts = dict.fromkeys(keys, 0)
        for name, count in mix.items():
            target = names.get(name, name)
            counts[target] = counts.get(target, 0) + count
        return counts


class StoredRenames:
    """Applies both renames to the stored lessons, through the models of the migration's own state."""

    #: (model, column) → what is rewritten there; every JSON column of the lessons app is named in one of the two lists
    DIFFICULTY_COLUMNS: ClassVar[tuple[tuple[str, str], ...]] = (
        ("Lesson", "final_test"), ("Lesson", "plan"), ("StudyMaterial", "content"),
    )  # fmt: skip
    LEVEL_COLUMNS: ClassVar[tuple[tuple[str, str], ...]] = (("Lesson", "assessment"), ("Lesson", "plan"))
    #: JSON columns that hold neither a level nor a difficulty
    UNTOUCHED_COLUMNS: ClassVar[tuple[tuple[str, str], ...]] = (
        ("Lesson", "prerequisites_to_cover"), ("Lesson", "pages"), ("Lesson", "interactive_plan"),
        ("Lesson", "code_parts"), ("Lesson", "warnings"), ("Lesson", "config_snapshot"),
        ("Lesson", "settings_snapshot"),
        ("Quiz", "questions"), ("Quiz", "prerequisites"), ("QuizAttempt", "answers"), ("QuizAttempt", "result"),
        ("TestSubmission", "answers"), ("TestSubmission", "result"), ("GraphRun", "payload"),
        ("GraphRun", "node_status"), ("GraphRun", "node_timings"), ("LessonVersion", "code_parts"),
        ("FlowSettings", "media_sources"), ("FlowSettings", "allowed_media_licenses"),
        # added by migration 0007, after the rename: they are written in the new names from the start
        ("Lesson", "test_blueprint"), ("Question", "payload"), ("TestSubmission", "questions"),
        ("TestSubmission", "followup"),
        ("Lesson", "recommended_from"),  # added by migration 0011: an attempt id and a topic
        ("Lesson", "concept_index"),  # added by migration 0017: concepts, pages and headings
    )  # fmt: skip

    def __init__(self, levels: LevelRename | None = None, difficulties: DifficultyRename | None = None):
        self.levels = levels or LevelRename()
        self.difficulties = difficulties or DifficultyRename()

    def forward(self, apps) -> None:
        self._apply(apps, self.levels.forward_name, self.levels.forward_document, self.difficulties.forward)

    def backward(self, apps) -> None:
        self._apply(apps, self.levels.backward_name, self.levels.backward_document, self.difficulties.backward)

    def _apply(self, apps, level_name, level_document, difficulty) -> None:
        lessons = apps.get_model("lessons", "Lesson")
        for lesson in lessons.objects.iterator(chunk_size=200):
            fields = {
                "level": level_name(lesson.level),
                "assessment": level_document(lesson.assessment),
                "final_test": difficulty(lesson.final_test),
                "plan": difficulty(level_document(lesson.plan)),
            }
            changed = [name for name, value in fields.items() if value != getattr(lesson, name)]
            if changed:
                for name in changed:
                    setattr(lesson, name, fields[name])
                lesson.save(update_fields=changed)
        materials = apps.get_model("lessons", "StudyMaterial")
        for material in materials.objects.iterator(chunk_size=200):
            content = difficulty(material.content)
            if content != material.content:
                material.content = content
                material.save(update_fields=["content"])
