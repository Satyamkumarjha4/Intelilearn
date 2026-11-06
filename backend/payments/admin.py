"""The payments screens of the Django admin. Orders and their events are read-only: money is taken and credits are
given by the payment path, never by a form. What an administrator may do is ask for a refund (credits plan D14)."""

from django.contrib import admin, messages

from console.audit import AuditTrail

from .errors import NotSupported, PaymentError
from .models import PaymentEventLog, PaymentOrder
from .registry import PaymentGateways


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.action(description="Refund the rest of the selected payments")
def refund(modeladmin, request, queryset):
    """Refund through the provider when the gateway can, else say where to do it. Either way the credits are taken back
    when the provider's refund event arrives (D14), not here, so what is refunded is always what the provider says."""
    gateways = PaymentGateways()
    for order in queryset.select_related("user"):
        label = f"{order.user} ({order.pk})"
        if order.status != PaymentOrder.Status.FULFILLED:
            modeladmin.message_user(
                request, f"{label}: only a payment that was fulfilled can be refunded.", messages.ERROR
            )
            continue
        left = order.amount_paise - order.refunded_paise
        gateway = gateways.lookup(order.gateway)
        if left <= 0:
            modeladmin.message_user(request, f"{label}: it is refunded in full already.", messages.WARNING)
        elif gateway is None or not gateway.can_refund or not order.payment_ref:
            name = gateway.display_name if gateway else order.gateway
            modeladmin.message_user(
                request,
                f"{label}: refund it in {name}'s own dashboard. "
                f"The credits are taken back when {name} says it was refunded.",
                messages.WARNING,
            )
        else:
            try:
                result = gateway.refund(order.payment_ref, left)
            except (NotSupported, PaymentError) as error:
                modeladmin.message_user(request, f"{label}: the refund was not made ({error}).", messages.ERROR)
                continue
            AuditTrail(request.user).record(
                "payments.refund", "payment_order", order.pk,
                after={"amount_paise": result.amount_paise, "refund_ref": result.refund_ref, "gateway": order.gateway},
            )  # fmt: skip
            modeladmin.message_user(
                request,
                f"{label}: a refund of {result.amount_paise / 100:.2f} rupees was asked for. "
                "The credits come back when the provider confirms it.",
                messages.SUCCESS,
            )  # fmt: skip


@admin.register(PaymentOrder)
class PaymentOrderAdmin(ReadOnlyAdmin):
    list_display = ["id", "user", "gateway", "amount_paise", "refunded_paise", "status", "created_at"]
    list_filter = ["status", "gateway"]
    search_fields = ["user__email", "provider_ref", "payment_ref"]
    date_hierarchy = "created_at"
    list_select_related = ["user"]
    actions = [refund]


@admin.register(PaymentEventLog)
class PaymentEventLogAdmin(ReadOnlyAdmin):
    list_display = ["id", "gateway", "event_id", "kind", "outcome", "amount_paise", "shortfall", "received_at"]
    list_filter = ["gateway", "kind", "outcome"]
    search_fields = ["event_id", "provider_ref"]
    date_hierarchy = "received_at"
