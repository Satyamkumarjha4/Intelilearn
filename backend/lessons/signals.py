from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import MediaAsset


@receiver(post_delete, sender=MediaAsset)
def delete_media_file(sender, instance: MediaAsset, **kwargs):
    # Also runs for assets removed by a lesson's cascade delete.
    if instance.file:
        instance.file.storage.delete(instance.file.name)
