"""The payments screens of the Django admin. Orders and their events are read-only: money is taken and credits are
given by the payment path, never by a form. What an administrator may do is ask for a refund (credits plan D14)."""

import uuid

from django import forms
from django.contrib import admin, messages
from django.contrib.admin.helpers import ActionForm

from .models import PaymentEventLog, PaymentOrder
from .refunds import RefundDesk, RefundOutcome, RupeeAmount


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class RefundActionForm(ActionForm):
    """The action bar of the order list, with two more fields. The token is made when the list is shown (the callable
    is evaluated at each render), travels with the submit, and is what lets the server refund a submission once. The
    amount is rupees for one payment, blank for all that remains. Both are read leniently: a bad one is a message, not
    a form that silently does nothing."""

    refund_token = forms.CharField(required=False, widget=forms.HiddenInput, initial=lambda: str(uuid.uuid4()))
    refund_amount = forms.CharField(
        required=False,
        label="Refund (₹):",
        widget=forms.TextInput(attrs={"size": 8, "placeholder": "the rest"}),
    )


class RefundNotices:
    """The administrator's words for each way a refund can end."""

    def __init__(self, modeladmin, request, label: str):
        self.send = lambda text, level: modeladmin.message_user(request, f"{label}: {text}", level)

    def tell(self, outcome: RefundOutcome) -> None:
        getattr(self, f"_{outcome.kind}")(outcome)

    def _not_fulfilled(self, outcome):
        self.send("only a payment that was fulfilled can be refunded.", messages.ERROR)

    def _in_full(self, outcome):
        self.send("it is refunded in full already.", messages.WARNING)

    def _all_asked(self, outcome):
        self.send(
            "there is nothing left to ask for: the rest has been asked for and is waiting for the provider.",
            messages.WARNING,
        )

    def _too_much(self, outcome):
        self.send(
            f"the amount is more than what remains to refund (₹{outcome.amount_paise / 100:.2f}).", messages.ERROR
        )

    def _duplicate(self, outcome):
        self.send(
            "this refund was already asked for (the form was sent twice). Nothing more was asked.", messages.WARNING
        )

    def _dashboard(self, outcome):
        name = outcome.provider
        self.send(
            f"refund it in {name}'s own dashboard. The credits are taken back when {name} says it was refunded.",
            messages.WARNING,
        )

    def _failed(self, outcome):
        self.send(f"the refund was not made ({outcome.error}).", messages.ERROR)

    def _asked(self, outcome):
        self.send(
            f"a refund of {outcome.amount_paise / 100:.2f} rupees was asked for. "
            "The credits come back when the provider confirms it.",
            messages.SUCCESS,
        )


@admin.action(description="Refund the selected payments (the rest of each, or the amount typed for one)")
def refund(modeladmin, request, queryset):
    """Ask the provider to refund each selected payment, through `RefundDesk`. Either way the credits are taken back
    when the provider's refund event arrives (D14), not here, so what is refunded is always what the provider says."""
    desk = RefundDesk()
    token = RefundToken.read(request.POST.get("refund_token", ""))
    orders = list(queryset.select_related("user"))
    try:
        amount = RupeeAmount.to_paise(request.POST.get("refund_amount", ""))
    except ValueError:
        modeladmin.message_user(request, "Enter the amount in rupees, like 12.50.", messages.ERROR)
        return
    if amount is not None and len(orders) != 1:
        modeladmin.message_user(request, "An amount can only be given for one payment at a time.", messages.ERROR)
        return
    for order in orders:
        outcome = desk.refund(order.pk, request.user, token, amount)
        RefundNotices(modeladmin, request, f"{order.user} ({order.pk})").tell(outcome)


@admin.register(PaymentOrder)
class PaymentOrderAdmin(ReadOnlyAdmin):
    list_display = ["id", "user", "gateway", "amount_paise", "refunded_paise", "status", "created_at"]
    list_filter = ["status", "gateway"]
    search_fields = ["user__email", "provider_ref", "payment_ref"]
    date_hierarchy = "created_at"
    list_select_related = ["user"]
    actions = [refund]
    action_form = RefundActionForm


@admin.register(PaymentEventLog)
class PaymentEventLogAdmin(ReadOnlyAdmin):
    list_display = ["id", "gateway", "event_id", "kind", "outcome", "amount_paise", "shortfall", "received_at"]
    list_filter = ["gateway", "kind", "outcome"]
    search_fields = ["event_id", "provider_ref"]
    date_hierarchy = "received_at"


class RefundToken:
    @staticmethod
    def read(text: str) -> uuid.UUID | None:
        """The form's token, or `None` for none or a bad one (the submission is then not de-duplicated)."""
        try:
            return uuid.UUID(text.strip())
        except ValueError:
            return None
