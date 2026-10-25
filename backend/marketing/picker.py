import random

from django.conf import settings
from django.core.cache import cache as default_cache

from .models import DemoQuestion


class DemoQuestionPicker:
    """Chooses the hero card's next question: random among the active ones, and not the one just seen, with its options
    in a random order.

    The ids of the active questions are cached (ten minutes by default) so a page load costs one small query, and are
    cleared whenever a question is saved or deleted in the admin (see signals.py)."""

    CACHE_KEY = "marketing:demo_question_ids"

    def __init__(self, *, cache=None, rng: random.Random | None = None, ttl_s: int | None = None):
        self._cache = cache if cache is not None else default_cache
        self._rng = rng if rng is not None else random.Random()
        self._ttl_s = ttl_s if ttl_s is not None else settings.LANDING_DEMO_IDS_TTL_S

    def pick(self, exclude: int | None = None) -> DemoQuestion | None:
        """A random active question other than `exclude` (that one only if it is all there is), or None."""
        for fresh in (False, True):
            ids = self._ids(refresh=fresh)
            if not ids:
                return None
            candidates = [pk for pk in ids if pk != exclude] or ids
            if question := DemoQuestion.objects.filter(pk=self._rng.choice(candidates), is_active=True).first():
                return self._shuffled(question)
            # The cached id is gone (deleted or switched off behind the cache): read the list again, once.
        return None

    def _shuffled(self, question: DemoQuestion) -> DemoQuestion:
        """The same question with its options in a random order and `correct_index` following the right text. Only this
        copy changes (it is never saved): the bank is written with the answer wherever it fell, and a card that always
        had it in the same place would teach visitors to ignore the question."""
        order = list(range(len(question.options)))
        self._rng.shuffle(order)
        question.options = [question.options[i] for i in order]
        question.correct_index = order.index(question.correct_index)
        return question

    def invalidate(self) -> None:
        self._cache.delete(self.CACHE_KEY)

    def _ids(self, *, refresh: bool) -> list[int]:
        ids = None if refresh else self._cache.get(self.CACHE_KEY)
        if ids is None:
            ids = list(DemoQuestion.objects.filter(is_active=True).values_list("pk", flat=True))
            self._cache.set(self.CACHE_KEY, ids, timeout=self._ttl_s)
        return ids
