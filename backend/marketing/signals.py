from django.db.models.signals import post_delete, post_save

from .models import Testimonial
from .testimonials import PublicTestimonials


def _clear_testimonials(sender, **kwargs):
    PublicTestimonials.clear()


post_save.connect(_clear_testimonials, sender=Testimonial, dispatch_uid="marketing_testimonial_saved")
post_delete.connect(_clear_testimonials, sender=Testimonial, dispatch_uid="marketing_testimonial_deleted")
