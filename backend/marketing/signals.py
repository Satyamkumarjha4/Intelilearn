from django.db.models.signals import post_delete, post_save

from .models import DemoQuestion
from .picker import DemoQuestionPicker


def _clear_ids(sender, **kwargs):
    DemoQuestionPicker().invalidate()


post_save.connect(_clear_ids, sender=DemoQuestion, dispatch_uid="marketing_demo_question_saved")
post_delete.connect(_clear_ids, sender=DemoQuestion, dispatch_uid="marketing_demo_question_deleted")
