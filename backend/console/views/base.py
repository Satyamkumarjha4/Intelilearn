"""What every console view shares: staff-only access (404 for anyone else), a per-user rate limit, no caching, and
the audit trail of the signed-in staff member. Views parse, call a service and format; the services decide."""

from rest_framework import generics
from rest_framework.views import APIView

from console.access import ConsolePermission, ConsoleRateThrottle
from console.audit import AuditTrail

CONSOLE_TAG = ["console"]


class ConsoleAccess:
    """Mixin for any DRF view of the console."""

    permission_classes = [ConsolePermission]
    throttle_classes = [ConsoleRateThrottle]

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"  # operational data: never kept by a browser or a proxy
        return response

    @property
    def audit(self) -> AuditTrail:
        return AuditTrail(self.request.user)


class ConsoleView(ConsoleAccess, APIView):
    pass


class ConsoleListView(ConsoleAccess, generics.ListAPIView):
    """A paged list (cursor pagination: set `pagination_class`, whose `ordering` must be a stable field)."""
