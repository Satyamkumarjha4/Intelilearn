from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Profile, User


@receiver(post_save, sender=User)
def create_profile(sender, instance, created, raw=False, using=None, **kwargs):
    # raw: loaddata / the Supabase sync copy profiles themselves.
    if created and not raw:
        Profile.objects.using(using).get_or_create(user=instance)
