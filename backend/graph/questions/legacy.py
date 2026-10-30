"""Reads questions written before criteria existed as if they had them.

An old short answer lists `key_points`, an old long answer a `rubric` of sentences, and an old code question only a
reference solution. The grader and the result screen work in criteria that each carry marks, so the adapter derives
them on read. Stored data is never rewritten: an old attempt re-renders from what it was.
"""

from typing import ClassVar

COMPLETE = "The answer is complete and correct."
CODE = "The code does what the question asks, judged against the reference solution and the test cases."


class LegacyQuestionAdapter:
    #: kind → the old field that listed what a good answer contains
    POINTS: ClassVar[dict[str, str | None]] = {"short_answer": "key_points", "long_answer": "rubric", "code": None}

    @classmethod
    def normalise(cls, question: dict) -> dict:
        """The question with `criteria`, derived when it has none. Other kinds, and questions that have them, are as
        they were. The input is not changed."""
        if question.get("criteria") or question["type"] not in cls.POINTS:
            return question
        marks = question["marks"]
        field = cls.POINTS[question["type"]]
        if field is None:
            texts = [CODE]
        else:
            texts = [point for point in (question.get(field) or []) if str(point).strip()] or [COMPLETE]
        groups = cls._group(texts, marks)
        shares = cls._split(marks, len(groups))
        return {
            **question,
            "criteria": [{"text": "; ".join(g), "marks": m} for g, m in zip(groups, shares, strict=True)],
        }

    @staticmethod
    def _group(texts: list[str], marks: int) -> list[list[str]]:
        """At most one group per mark, so every criterion can be worth at least one."""
        count = min(len(texts), marks)
        size, extra = divmod(len(texts), count)
        groups, start = [], 0
        for index in range(count):
            end = start + size + (1 if index < extra else 0)
            groups.append(texts[start:end])
            start = end
        return groups

    @staticmethod
    def _split(marks: int, count: int) -> list[int]:
        """Evenly, the remainder going one mark each to the first criteria."""
        base, extra = divmod(marks, count)
        return [base + (1 if index < extra else 0) for index in range(count)]
