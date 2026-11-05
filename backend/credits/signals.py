"""The signup grant is given when an account is ready (credits plan D15); the receiver only calls `SignupGrant`."""

from django.dispatch import receiver

from accounts.signals import account_ready

from .earning.signup import SignupGrant


@receiver(account_ready, dispatch_uid="credits-signup-grant")
def give_signup_credits(sender, user, **kwargs):
    SignupGrant().on_account_ready(user)
