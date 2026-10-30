"""Keeps a retake from repeating a question. No model call: an exact repeat has the same normalised text, a near
repeat shares nearly all its words."""

import hashlib
import re
from dataclasses import dataclass, field

_SENTENCE_PUNCTUATION = re.compile(r"[.,;:!?\"'`_]")
_WORD = re.compile(r"[^\W_]+|[^\w\s]", re.UNICODE)


class StemHash:
    """The hash of a question's text. Case, spacing and sentence punctuation do not matter; the maths in it does
    (`$2+3$` is not `$2-3$`), so the symbols stay."""

    @staticmethod
    def normalise(text: str) -> str:
        return re.sub(r"\s+", " ", _SENTENCE_PUNCTUATION.sub(" ", text.lower())).strip()

    @classmethod
    def of(cls, text: str) -> str:
        return hashlib.sha256(cls.normalise(text).encode()).hexdigest()


@dataclass
class DedupeResult:
    kept: list[dict] = field(default_factory=list)
    dropped: list[tuple[dict, str]] = field(default_factory=list)  # (the question, why)


class QuestionDeduper:
    """Decides in order, so of two questions that repeat each other the earlier one is kept."""

    NEAR = 0.8  # the share of words two questions have in common (Jaccard) from which they count as the same

    ASKED = "asked before"
    NEAR_ASKED = "almost the same as a question asked before"
    REPEATS = "repeats another question in this set"

    def fresh(self, candidates: list[dict], excluded: list[str]) -> DedupeResult:
        """The candidates that are new, given every stem already asked. The inputs are not changed."""
        asked = [self._signature(text) for text in excluded]
        result = DedupeResult()
        kept: list[tuple[str, frozenset]] = []
        for candidate in candidates:
            signature = self._signature(candidate["question"])
            if reason := self._repeat(signature, asked, self.ASKED, self.NEAR_ASKED) or self._repeat(
                signature, kept, self.REPEATS, self.REPEATS
            ):
                result.dropped.append((candidate, reason))
            else:
                result.kept.append(candidate)
                kept.append(signature)
        return result

    def _signature(self, text: str) -> tuple[str, frozenset]:
        normal = StemHash.normalise(text)
        return normal, frozenset(_WORD.findall(normal))

    def _repeat(self, signature, others, exact_reason: str, near_reason: str) -> str | None:
        normal, words = signature
        for other_normal, other_words in others:
            if normal == other_normal:
                return exact_reason
            union = words | other_words
            if union and len(words & other_words) / len(union) >= self.NEAR:
                return near_reason
        return None
