from django.db.models.signals import post_delete, post_save

from .models import DemoQuestion, Testimonial
from .picker import DemoQuestionPicker
from .testimonials import PublicTestimonials


def _clear_ids(sender, **kwargs):
    DemoQuestionPicker().invalidate()


post_save.connect(_clear_ids, sender=DemoQuestion, dispatch_uid="marketing_demo_question_saved")
post_delete.connect(_clear_ids, sender=DemoQuestion, dispatch_uid="marketing_demo_question_deleted")


def _clear_testimonials(sender, **kwargs):
    PublicTestimonials.clear()


post_save.connect(_clear_testimonials, sender=Testimonial, dispatch_uid="marketing_testimonial_saved")
post_delete.connect(_clear_testimonials, sender=Testimonial, dispatch_uid="marketing_testimonial_deleted")
