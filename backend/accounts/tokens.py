"""Ending every session of an account (a password reset, and later a Google take-over)."""

from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from .models import User


class RefreshTokens:
    @staticmethod
    def revoke_all(user: User) -> int:
        """Blacklists every refresh token the account has, so none can be renewed. Returns how many were newly revoked.
        An access token already issued lives out its 30 minutes (the same as at sign-out)."""
        live = OutstandingToken.objects.filter(user=user, blacklistedtoken__isnull=True)
        rows = [BlacklistedToken(token=token) for token in live]
        BlacklistedToken.objects.bulk_create(rows, ignore_conflicts=True)
        return len(rows)
