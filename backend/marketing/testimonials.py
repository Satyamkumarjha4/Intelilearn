"""The testimonials the landing page may show, and the short cache in front of them."""

from django.core.cache import cache

from .models import Testimonial


class PublicTestimonials:
    """What an anonymous visitor may see: real, published testimonials the learner consented to, in position order.

    The rule is in the query, not in DEBUG or any setting, so a development database full of samples can never reach a
    public page by a mistaken configuration. Cached for a minute and cleared by every save and delete."""

    CACHE_KEY = "public:testimonials"
    TTL_S = 60

    def listing(self) -> list[dict]:
        shown = cache.get(self.CACHE_KEY)
        if shown is None:
            rows = Testimonial.objects.filter(is_published=True, consent_confirmed=True, is_sample=False)
            shown = [{"name": r.name, "context": r.context, "quote": r.quote, "rating": r.rating} for r in rows]
            cache.set(self.CACHE_KEY, shown, self.TTL_S)
        return shown

    @classmethod
    def clear(cls) -> None:
        cache.delete(cls.CACHE_KEY)
