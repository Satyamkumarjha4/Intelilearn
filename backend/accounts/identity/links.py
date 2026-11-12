"""Which accounts sign in with a provider (Google) instead of, or as well as, a password."""

from ..models import ExternalIdentity, User


class IdentityLinks:
    @staticmethod
    def has_identity(user: User) -> bool:
        return ExternalIdentity.objects.filter(user=user).exists()

    @classmethod
    def signs_in_only_with_a_provider(cls, user: User) -> bool:
        """A linked identity and no password: there is no password to reset, and none is added (plan D11)."""
        return not user.has_usable_password() and cls.has_identity(user)
