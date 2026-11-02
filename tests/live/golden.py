"""What a good lesson looks like, as checks that do not depend on the exact words a model chose.

`LessonChecks` is pure: it reads a lesson's data (pages, test, code, warnings) and lists what is wrong with it. The
live suite (`test_golden_topics.py`) runs the real flow on each `GoldenTopic` and applies it;
`test_golden_checks.py` tests the checks themselves offline, so a change to them is caught by `make check` without
calling a model.
"""

import re
from dataclasses import dataclass

from graph.normal import Normal
from graph.questions import ExpressionError, ExpressionEvaluator, TopicTraits
from graph.schemas.diagnostic import BANDS
from graph.validators.base import TextRules


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
    #: the test is a fixed blueprint (D15): multiple choice and multiple select for every topic, numerical as well for a
    #: calculation topic, so two kinds is what a history lesson has
    MIN_QUESTION_TYPES = 2
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


# --- the question quality checks (phase 9.8, plan §15.4) ------------------------------------------------------------
# Each class reads stored data and lists what is wrong with it in plain words, so a failed run says what to look at.


class QuestionChecks:
    """What makes a stored question a good one of its kind, beyond what the validators accept: the live suite applies
    these to what a real model really wrote, as the product stored it."""

    def problems(self, questions: list[dict]) -> list[str]:
        found = []
        for question in questions:
            check = getattr(self, f"_{question['type']}", None)
            if check:
                found += [f"{question['id']} ({question['type']}): {problem}" for problem in check(question)]
        return found

    @staticmethod
    def _mcq(q: dict) -> list[str]:
        options = q.get("options") or []
        found = [] if len(options) == 4 else [f"has {len(options)} options, not 4"]
        if not isinstance(q.get("correct_index"), int) or not 0 <= q["correct_index"] < len(options):
            found.append("its correct_index is not one of its options")
        if len({o.strip().lower() for o in options}) != len(options):
            found.append("two options are the same")
        return found

    @staticmethod
    def _msq(q: dict) -> list[str]:
        options, right = q.get("options") or [], q.get("correct_indices") or []
        found = [] if 4 <= len(options) <= 6 else [f"has {len(options)} options, not 4 to 6"]
        if len(set(right)) < 2:
            found.append(f"has {len(set(right))} correct option(s); a multiple-select question needs at least 2")
        if len(set(right)) != len(right) or any(not 0 <= i < len(options) for i in right):
            found.append("its correct options repeat or point outside its options")
        if right and len(set(right)) == len(options):
            found.append("every option is correct")
        return found

    @staticmethod
    def _numerical(q: dict) -> list[str]:
        try:
            value = ExpressionEvaluator().evaluate(q.get("answer_expr"))
        except ExpressionError as exc:
            return [f"its answer_expr {q.get('answer_expr')!r} does not evaluate: {exc}"]
        stored = q.get("answer")
        if stored is None or abs(stored - round(value, q.get("decimal_precision") or 0)) > 1e-9:
            return [f"its stored answer {stored!r} is not the value of {q['answer_expr']!r} ({value})"]
        return []

    @staticmethod
    def _rubric(q: dict) -> list[str]:
        criteria = q.get("criteria") or []
        found = [] if criteria else ["has no criteria"]
        if criteria and sum(c["marks"] for c in criteria) != q["marks"]:
            found.append(f"its criteria add up to {sum(c['marks'] for c in criteria)}, not its {q['marks']} marks")
        if any(c["marks"] < 1 for c in criteria):
            found.append("a criterion is worth no marks")
        if not str(q.get("model_answer", "")).strip():
            found.append("has no model answer")
        return found

    _short_answer = _long_answer = _rubric


class ConceptChecks:
    """A question about a lesson names one of the lesson's own concepts, so a weak concept can be linked to a page."""

    @staticmethod
    def problems(questions: list[dict], allowed: list[str]) -> list[str]:
        names = {Normal.text(name) for name in allowed}
        return [
            f"{q['id']} names the concept {q.get('concept')!r}, which the lesson does not have"
            for q in questions
            if Normal.text(str(q.get("concept", ""))) not in names
        ]


class PoolChecks:
    """The calibration pool: two valid multiple-choice questions for each of the five bands, nothing else."""

    PER_BAND = 2

    def problems(self, pool: list[dict]) -> list[str]:
        found = []
        for band in BANDS:
            asked = [q for q in pool if q.get("band") == band]
            if len(asked) != self.PER_BAND:
                found.append(f"band {band!r} has {len(asked)} questions, not {self.PER_BAND}")
        if extra := [q for q in pool if q.get("band") not in BANDS]:
            found.append(f"{len(extra)} question(s) have no known band")
        for q in pool:
            options = q.get("options") or []
            if len(options) != 4 or not isinstance(q.get("correct_index"), int) or not 0 <= q["correct_index"] < 4:
                found.append(f"{q.get('id')} is not a valid multiple-choice question")
        return found


class TraitChecks:
    """A topic's traits, judged by the real model, against what any person would say."""

    EXPECTED = (
        ("Quadratic equations", True, False),
        ("Kinematics: speed, velocity and acceleration", True, False),
        ("Python list comprehensions", False, True),
        ("The causes of the French Revolution", False, False),
    )

    def problems(self, judged: dict[str, TopicTraits | None]) -> list[str]:
        found = []
        for topic, quantitative, programming in self.EXPECTED:
            traits = judged.get(topic)
            if traits is None:
                found.append(f"{topic!r}: the model did not answer")
            elif (traits.quantitative, traits.programming) != (quantitative, programming):
                found.append(
                    f"{topic!r}: judged quantitative={traits.quantitative}, programming={traits.programming}; "
                    f"expected {quantitative}, {programming}"
                )
        return found


class PlanChecks:
    """`lesson.plan`'s quantitative flag, which decides whether a lesson's test has numerical questions."""

    EXPECTED = (("Solving quadratic equations", True), ("The causes of the French Revolution", False))

    def problems(self, flags: dict[str, bool | None]) -> list[str]:
        return [
            f"{topic!r}: the plan says quantitative={flags.get(topic)}, expected {expected}"
            for topic, expected in self.EXPECTED
            if flags.get(topic) is not expected
        ]


class DedupeChecks:
    """A retake must not ask the same thing again in other words. The product's deduper drops a question at a word
    overlap of 0.8; this looks for the near-misses just under it, which a person would still call a repeat."""

    LOOSE = 0.6

    def problems(self, earlier: list[dict], later: list[dict]) -> list[str]:
        found = []
        before = [self._words(q["question"]) for q in earlier]
        for q in later:
            words = self._words(q["question"])
            best = max((self._overlap(words, other) for other in before), default=0.0)
            if best >= self.LOOSE:
                found.append(
                    f"{q['id']} shares {best:.0%} of its words with a question asked before: {q['question'][:90]!r}"
                )
        return found

    @staticmethod
    def _words(text: str) -> frozenset[str]:
        return frozenset(Normal.text(text).split())

    @staticmethod
    def _overlap(a: frozenset[str], b: frozenset[str]) -> float:
        return len(a & b) / len(a | b) if a | b else 0.0


class SheetChecks:
    """The revision sheet's concept-coverage rule, measured on a real lesson: how many of the lesson's concepts the
    sheet's text mentions, by the same test `StudyMaterialValidator` uses."""

    @staticmethod
    def texts(content: dict) -> list[str]:
        texts = []
        for sub in content.get("subtopics", []):
            texts += [sub["title"], sub["summary"], *sub["key_points"], *sub["common_mistakes"]]
            texts += [part for ex in sub["worked_examples"] for part in (ex["problem"], ex["solution"])]
        return texts

    def missing(self, content: dict, concepts: list[str]) -> list[str]:
        texts = self.texts(content)
        return [c for c in concepts if not any(TextRules.mentions(t, c) for t in texts)]

    def problems(self, content: dict, concepts: list[str]) -> list[str]:
        """The rule as the product states it: more than a third of the concepts missing is a failure."""
        missing = self.missing(content, concepts)
        if len(missing) > len(concepts) // 3:
            return [f"the revision sheet misses {len(missing)} of {len(concepts)} concepts: {'; '.join(missing)}"]
        return []
