"""`manage.py seed_sample_testimonials`: three placeholder testimonials for a developer's machine, so the landing page
can be designed against a full "What learners say" section. They are samples (unpublished, no consent): the database
refuses to publish one and the public endpoint never returns one. Refuses to run unless DEBUG is on."""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Max

from marketing.models import Testimonial

SAMPLES = [
    (
        "[Learner name]",
        "[Class 12 student]",
        "I skipped the chapter I already knew and spent the evening on the part I kept getting wrong.",
        5,
    ),
    (
        "[Learner name]",
        "[B.Tech, 2nd year]",
        "The retake had completely new questions, so I could tell I had actually learned it.",
        5,
    ),
    (
        "[Learner name]",
        "[Class 10 student]",
        "The revision sheet was the one page I read on the bus before my exam.",
        None,
    ),
]


class Command(BaseCommand):
    help = "Make three placeholder (sample) testimonials for local development. Refuses unless DEBUG is on."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Sample testimonials are for local development only: DEBUG is off, so nothing was made.")
        known = set(Testimonial.objects.filter(is_sample=True).values_list("quote", flat=True))
        position = Testimonial.objects.aggregate(top=Max("position"))["top"] or 0
        made = 0
        for name, context, quote, rating in SAMPLES:
            if quote in known:
                continue
            position += 1
            Testimonial.objects.create(
                name=name, context=context, quote=quote, rating=rating, position=position, is_sample=True
            )
            made += 1
        self.stdout.write(f"Made {made} sample testimonial(s). They stay unpublished and never reach the public page.")
