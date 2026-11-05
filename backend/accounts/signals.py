from django.db.models.signals import post_save
from django.dispatch import Signal, receiver

from .models import Profile, User

#: Sent when a person has an account they can use: at registration today, and when their email is confirmed once
#: sign-in is built (credits plan, phase 11). Receivers get `user`. The signup credits hang from this, not from
#: "registered", so verifying email later changes the sender and nothing else.
account_ready = Signal()


@receiver(post_save, sender=User)
def create_profile(sender, instance, created, raw=False, using=None, **kwargs):
    # raw: loaddata / the Supabase sync copy profiles themselves.
    if created and not raw:
        Profile.objects.using(using).get_or_create(user=instance)
