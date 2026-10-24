"""What a good lesson looks like, as checks that do not depend on the exact words a model chose.

`LessonChecks` is pure: it reads a lesson's data (pages, test, code, warnings) and lists what is wrong with it. The
live suite (`test_golden_topics.py`) runs the real flow on each `GoldenTopic` and applies it;
`test_golden_checks.py` tests the checks themselves offline, so a change to them is caught by `make check` without
calling a model.
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class GoldenTopic:
    topic: str
    #: words a lesson on this topic cannot avoid; at least `min_keywords` must appear in the pages
    keywords: tuple[str, ...]
    min_keywords: int = 2
    #: a topic that is best taught with a real picture (the lesson should have found one)
    wants_picture: bool = False


GOLDEN_TOPICS = [
    GoldenTopic("Binary search", ("sorted", "middle", "half", "halv", "log"), min_keywords=3),
    GoldenTopic(
        "Asexual reproduction", ("offspring", "fission", "budding", "clone", "genetically"), wants_picture=True
    ),
    GoldenTopic("Photosynthesis", ("chlorophyll", "light", "glucose", "carbon dioxide", "oxygen"), min_keywords=3),
]


class LessonChecks:
    PAGES = ("introduction", "core", "advanced")
    MIN_SECTIONS = 3
    MIN_WORDS_PER_PAGE = 150
    MIN_QUESTIONS = 8
    MIN_QUESTION_TYPES = 3
    MAX_WARNINGS = 3
    LEAKS = re.compile(r"lorem ipsum|\bTODO\b|as an ai language model|\[insert|<placeholder", re.I)

    def problems(self, lesson: dict, golden: GoldenTopic) -> list[str]:
        """`lesson`: pages, final_test, code, code_parts, warnings, media (the number of stored media files)."""
        found = self._pages(lesson.get("pages") or {}, golden)
        found += self._test((lesson.get("final_test") or {}).get("questions", []))
        found += self._document(lesson)
        warnings = lesson.get("warnings") or []
        if len(warnings) > self.MAX_WARNINGS:
            found.append(f"The lesson came out with {len(warnings)} degradation warnings: {'; '.join(warnings[:3])} …")
        if golden.wants_picture and not lesson.get("media"):
            found.append(f"A lesson on {golden.topic} should have a real picture, and has none.")
        return found

    def _pages(self, pages: dict, golden: GoldenTopic) -> list[str]:
        found = [f"The {key} page is missing." for key in self.PAGES if key not in pages]
        texts = []
        for key in self.PAGES:
            page = pages.get(key)
            if not page:
                continue
            sections = page.get("sections", [])
            if len(sections) < self.MIN_SECTIONS:
                found.append(f"The {key} page has {len(sections)} sections; at least {self.MIN_SECTIONS} are expected.")
            text = " ".join([page.get("summary", "")] + [s["heading"] + " " + s["body"] for s in sections])
            if len(text.split()) < self.MIN_WORDS_PER_PAGE:
                found.append(f"The {key} page is thin: {len(text.split())} words.")
            if leak := self.LEAKS.search(text):
                found.append(f"The {key} page contains placeholder text: {leak.group(0)!r}.")
            texts.append(text.lower())
        used = [word for word in golden.keywords if any(word in text for text in texts)]
        if len(used) < golden.min_keywords:
            found.append(
                f"The pages hardly mention {golden.topic}: only {used or 'none'} of {list(golden.keywords)} appear."
            )
        return found

    def _test(self, questions: list[dict]) -> list[str]:
        found = []
        if len(questions) < self.MIN_QUESTIONS:
            found.append(f"The test has {len(questions)} questions; at least {self.MIN_QUESTIONS} are expected.")
        if len({q["type"] for q in questions}) < self.MIN_QUESTION_TYPES:
            found.append(f"The test uses fewer than {self.MIN_QUESTION_TYPES} kinds of question.")
        ids = [q["id"] for q in questions]
        if len(set(ids)) != len(ids):
            found.append("The test has repeated question ids.")
        if sum(q["marks"] for q in questions) <= 0:
            found.append("The test is worth no marks.")
        return found

    def _document(self, lesson: dict) -> list[str]:
        found = []
        if "function LessonDocument" not in (lesson.get("code") or ""):
            found.append("The lesson has no document to show.")
        parts = lesson.get("code_parts") or {}
        if set(parts.get("pages", {})) != set(self.PAGES):
            found.append("The stored code does not hold the three reading pages.")
        return found
