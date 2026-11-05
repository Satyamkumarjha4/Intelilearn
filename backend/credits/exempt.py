"""Who does not pay (credits plan D11, T12): a learner whose wallet is flagged `credits_exempt`, set by an
administrator and
off by default. Being staff does not exempt anyone. An exempt learner's work is still recorded, at 0 credits, with
the lines
it would have cost."""

from .models import Wallet


class ExemptPolicy:
    def applies_to(self, user) -> bool:
        """Reads the flag; a learner with no wallet yet is not exempt, and nothing is created."""
        return Wallet.objects.filter(pk=user.pk, credits_exempt=True).exists()
