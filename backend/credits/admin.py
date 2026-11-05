"""The credits screens of the Django admin (credits plan §10).

The ledger, the buckets and the holds are read-only: money moves through `Ledger`, never through a form. What an
administrator may do is edit the credit settings, switch a wallet's `credits_exempt` flag, and give or take credits with
the "Give or take credits" action, which asks for a reason and goes through the ledger.
"""

from django.contrib import admin, messages
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.template.response import TemplateResponse

from .errors import LedgerError
from .forms import AdjustCreditsForm
from .ledger import Ledger
from .models import CreditBucket, CreditHold, CreditSettings, CreditTransaction, Wallet


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CreditTransaction)
class CreditTransactionAdmin(ReadOnlyAdmin):
    list_display = ["id", "user", "type", "amount", "balance_after", "action", "created_at"]
    list_filter = ["type", "action"]
    search_fields = ["user__email", "idempotency_key"]
    date_hierarchy = "created_at"
    list_select_related = ["user"]


@admin.register(CreditBucket)
class CreditBucketAdmin(ReadOnlyAdmin):
    list_display = ["id", "user", "source", "amount_remaining", "amount_granted", "expires_at", "revoked_at"]
    list_filter = ["source"]
    search_fields = ["user__email"]
    list_select_related = ["user"]


@admin.register(CreditHold)
class CreditHoldAdmin(ReadOnlyAdmin):
    list_display = ["id", "user", "action", "amount", "status", "exempt", "created_at", "settled_at"]
    list_filter = ["status", "action", "exempt"]
    search_fields = ["user__email", "subject_id"]
    list_select_related = ["user"]


@admin.action(description="Give or take credits…")
def adjust_credits(modeladmin, request, queryset):
    """Give (positive) or take (negative) credits for the selected wallets. The first request draws the form; the
    second,
    sent with `apply`, moves the credits through the ledger if the form is valid, reason included."""
    form = AdjustCreditsForm(request.POST if "apply" in request.POST else None)
    if "apply" in request.POST and form.is_valid():
        ledger, done = Ledger(), 0
        for wallet in queryset.select_related("user"):
            key = f"admin:{form.cleaned_data['token']}:{wallet.pk}"
            try:
                ledger.adjust(
                    wallet.user_id, form.cleaned_data["amount"], key, reason=form.cleaned_data["reason"],
                    actor=request.user.email,
                )  # fmt: skip
                done += 1
            except LedgerError as exc:
                modeladmin.message_user(request, f"{wallet.user}: {exc}", messages.ERROR)
        if done:
            modeladmin.message_user(request, f"Credits moved for {done} wallet(s).", messages.SUCCESS)
        return None
    context = {
        **modeladmin.admin_site.each_context(request),
        "title": "Give or take credits",
        "form": form,
        "wallets": queryset.select_related("user"),
        "selected": request.POST.getlist(ACTION_CHECKBOX_NAME),
        "opts": modeladmin.model._meta,
    }
    return TemplateResponse(request, "admin/credits/adjust_credits.html", context)


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ["user", "credits_exempt", "balance", "reserved", "created_at"]
    list_filter = ["credits_exempt"]
    search_fields = ["user__email"]
    fields = ["user", "credits_exempt", "balance", "reserved", "created_at"]
    readonly_fields = ["user", "balance", "reserved", "created_at"]
    actions = [adjust_credits]
    list_select_related = ["user"]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Balance")
    def balance(self, wallet):
        return Ledger().balance(wallet.user_id)

    @admin.display(description="Reserved")
    def reserved(self, wallet):
        return Ledger().reserved(wallet.user_id)


@admin.register(CreditSettings)
class CreditSettingsAdmin(admin.ModelAdmin):
    """One row of amounts and windows. There is nothing to add or delete."""

    def has_add_permission(self, request):
        return not CreditSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
