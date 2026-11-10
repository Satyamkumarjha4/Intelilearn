"""The signup grant is given when an account is ready (credits plan D15); the receiver only calls `SignupGrant`."""

from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from accounts.signals import account_ready
from lessons.models import FlowSettings

from .earning.signup import SignupGrant
from .models import ActionPrice, CreditSettings, Plan
from .pricing.public import PublicPricing


@receiver(account_ready, dispatch_uid="credits-signup-grant")
def give_signup_credits(sender, user, **kwargs):
    SignupGrant().on_account_ready(user)


def _forget_public_pricing(sender, **kwargs):
    """The landing page's prices are cached for a minute; a saved price, plan or setting must show at once, and again
    once the transaction that saved it is over (so a read in between cannot cache the old numbers)."""
    PublicPricing.clear()
    transaction.on_commit(PublicPricing.clear)


for _model in (ActionPrice, CreditSettings, FlowSettings, Plan):
    post_save.connect(
        _forget_public_pricing, sender=_model, dispatch_uid=f"credits-public-pricing-saved-{_model.__name__}"
    )
    post_delete.connect(
        _forget_public_pricing, sender=_model, dispatch_uid=f"credits-public-pricing-deleted-{_model.__name__}"
    )
