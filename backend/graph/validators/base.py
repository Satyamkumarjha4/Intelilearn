"""What every validator shares: the port, the helpers for the checks that recur, and the composite.

A validator is pure: no ORM, no network. It returns the problems it found in plain language (an empty list means
valid), and the problems go back to the model as feedback on the retry, so each one says what to change.
Rules JSON Schema can't express ("2 questions per band", "concepts unique") live in validators, not in the schemas.
"""

import re
from collections import Counter
from collections.abc import Iterable
from typing import Any, Protocol


class LatexChecker(Protocol):
    def latex(self, expressions: list[str]) -> list[str]:
        """One message per expression that doesn't parse."""


class Validator(Protocol):
    def validate(self, subject: Any, **context: Any) -> list[str]:
        """The problems with `subject`. `context` carries what the rules need besides it (settings, a plan…)."""


class TextRules:
    """Checks on text and options that several validators apply."""

    CATCH_ALL = re.compile(r"\b(all|none|both|neither) of (the )?(above|these|them)\b|\ball the above\b", re.I)
    MATH = re.compile(r"\$\$(.+?)\$\$|\$([^$\n]+?)\$", re.S)

    @staticmethod
    def norm(text: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text.lower())).strip()

    @staticmethod
    def duplicates(values: Iterable[str]) -> list[str]:
        return [value for value, count in Counter(values).items() if count > 1]

    @classmethod
    def math_in(cls, text: str) -> list[str]:
        """LaTeX fragments inside $…$ / $$…$$ in a Markdown string."""
        return [(block or inline).strip() for block, inline in cls.MATH.findall(text or "")]

    @classmethod
    def mentions(cls, text: str, concept: str) -> bool:
        """Does the text talk about the concept? True when at least half of the concept's words appear."""
        words = [w for w in cls.norm(concept).split() if len(w) > 3] or cls.norm(concept).split()
        haystack = cls.norm(text)
        return sum(w in haystack for w in words) >= max(1, len(words) // 2)

    @classmethod
    def option_problems(cls, label: str, options: list[str]) -> list[str]:
        problems = []
        if len({cls.norm(o) for o in options}) != len(options):
            problems.append(f"{label}: options must all be different.")
        if any(cls.CATCH_ALL.search(o) for o in options):
            problems.append(f'{label}: don\'t use "all/none of the above" style options.')
        return problems


class LatexRules:
    """Asks the injected checker about maths. Without a checker (or without maths) there is nothing to report."""

    def __init__(self, checker: LatexChecker | None = None):
        self.checker = checker

    def problems(self, expressions: list[str]) -> list[str]:
        expressions = [e for e in expressions if e]
        return self.checker.latex(expressions) if self.checker and expressions else []


class CompositeValidator:
    """Several validators behave as one: the problems of the first part that finds any, so a costly later part
    (an LLM reviewer) only runs once the cheap deterministic parts pass."""

    def __init__(self, parts: Iterable[Validator]):
        self.parts = list(parts)

    def validate(self, subject: Any, **context: Any) -> list[str]:
        for part in self.parts:
            if problems := part.validate(subject, **context):
                return problems
        return []
