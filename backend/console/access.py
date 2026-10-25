"""Who may use the console API, and how often."""

from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAdminUser
from rest_framework.throttling import UserRateThrottle


class ConsolePermission(IsAdminUser):
    """Staff only. Everyone else, signed in or not, gets a 404 (not a 403), so the area does not announce itself."""

    def has_permission(self, request, view):
        if super().has_permission(request, view):
            return True
        raise NotFound()


class ConsoleRateThrottle(UserRateThrottle):
    """Per staff member (`CONSOLE_THROTTLE_RATE`, 120 a minute): a dashboard polls, but a runaway loop should stop."""

    scope = "console"
