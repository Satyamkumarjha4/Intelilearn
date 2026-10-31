"""The one reader for a stored blueprint of any kind: the graph state holds either a lesson test's or a quiz's."""

from .blueprint import LessonTestBlueprint
from .quiz_blueprint import QuizBlueprint


class Blueprints:
    @staticmethod
    def from_json(data) -> LessonTestBlueprint | QuizBlueprint:
        """A lesson test's blueprint has no `kind` (it was stored before there were other kinds); a quiz's says so."""
        if not isinstance(data, dict):
            raise ValueError("Not a stored blueprint")
        kind = data.get("kind")
        if kind is None:
            return LessonTestBlueprint.from_json(data)
        if kind == QuizBlueprint.KIND:
            return QuizBlueprint.from_json(data)
        raise ValueError(f"Unknown kind of blueprint: {kind!r}")
