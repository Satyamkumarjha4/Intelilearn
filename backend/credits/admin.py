"""The credits screens of the Django admin (credits plan §10).

The ledger, the buckets and the holds are read-only: money moves through `Ledger`, never through a form. What an
administrator may do is edit the credit settings, switch a wallet's `credits_exempt` flag, and give or take credits with
the "Give or take credits" action, which asks for a reason and goes through the ledger. Prices (`ActionPrice`) are
edited
here too: an edit adds a row and switches the old one off (`PriceCatalog`), so history is kept and nothing in flight
changes.
"""

import uuid

from django.contrib import admin, messages
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.db import transaction
from django.template.response import TemplateResponse

from console.audit import AuditTrail

from .clock import SystemClock
from .errors import LedgerError
from .forms import AdjustCreditsForm, GivePlanForm
from .ledger import Ledger
from .models import (
    ActionPrice,
    CreditBucket,
    CreditHold,
    CreditSettings,
    CreditTransaction,
    Plan,
    PlanPeriod,
    PlanPurchase,
    Wallet,
)
from .plans.desk import PurchaseDesk
from .plans.errors import InvalidPlanRequest, QueueFull
from .plans.fulfilment import PlanFulfilment
from .pricing.book import PriceCatalog


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
                with transaction.atomic():
                    before = ledger.balance(wallet.user_id)
                    moved = ledger.adjust(
                        wallet.user_id, form.cleaned_data["amount"], key, reason=form.cleaned_data["reason"],
                        actor=request.user.email,
                    )  # fmt: skip
                    if moved.created:  # the same form sent twice moves the credits once, and is recorded once
                        AuditTrail(request.user).record(
                            "credits.adjust", "wallet", wallet.pk,
                            before={"balance": before},
                            after={"balance": ledger.balance(wallet.user_id), "amount": form.cleaned_data["amount"],
                                   "reason": form.cleaned_data["reason"]},
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


@admin.action(description="Give a plan…")
def give_plan(modeladmin, request, queryset):
    """Put a plan on the selected wallets for nothing, with a reason: the whole path of a purchase before payments
    exist. Each
    gift is a purchase marked as an administrator's, is fulfilled like any other, and is written to the change log."""
    form = GivePlanForm(request.POST if "apply" in request.POST else None)
    if "apply" in request.POST and form.is_valid():
        data, desk, fulfilment = form.cleaned_data, PurchaseDesk(), PlanFulfilment()
        given = 0
        for wallet in queryset.select_related("user"):
            purchase_id = uuid.uuid5(data["token"], str(wallet.pk))  # the same form sent twice is the same purchase
            try:
                with transaction.atomic():
                    purchase = desk.open(
                        wallet.user, data["plan"], quantity=data["quantity"], credits=data["credits"], source="admin",
                        by=request.user.email, reason=data["reason"], purchase_id=purchase_id,
                    )  # fmt: skip
                    if fulfilment.fulfil(purchase).created:
                        AuditTrail(request.user).record(
                            "credits.give_plan", "wallet", wallet.pk,
                            after={"plan": data["plan"], "quantity": data["quantity"], "credits": data["credits"],
                                   "reason": data["reason"], "purchase": str(purchase.pk)},
                        )  # fmt: skip
                        given += 1
            except QueueFull as full:
                modeladmin.message_user(
                    request,
                    f"{wallet.user}: the plan queue is full "
                    f"({full.extra['open_periods']} of {full.extra['limit']} periods are open).",
                    messages.ERROR,
                )
            except InvalidPlanRequest as refused:
                modeladmin.message_user(request, f"{wallet.user}: {refused.detail}", messages.ERROR)
        if given:
            modeladmin.message_user(request, f"Gave the plan to {given} wallet(s).", messages.SUCCESS)
        return None
    context = {
        **modeladmin.admin_site.each_context(request),
        "title": "Give a plan",
        "form": form,
        "wallets": queryset.select_related("user"),
        "selected": request.POST.getlist(ACTION_CHECKBOX_NAME),
        "opts": modeladmin.model._meta,
    }
    return TemplateResponse(request, "admin/credits/give_plan.html", context)


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ["user", "credits_exempt", "balance", "reserved", "created_at"]
    list_filter = ["credits_exempt"]
    search_fields = ["user__email"]
    fields = ["user", "credits_exempt", "balance", "reserved", "created_at"]
    readonly_fields = ["user", "balance", "reserved", "created_at"]
    actions = [adjust_credits, give_plan]
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


@admin.register(ActionPrice)
class ActionPriceAdmin(admin.ModelAdmin):
    """The price table. A live price is edited by adding a row, so its history stays; an old price is read-only, and no
    price can be deleted. Switching a price off makes the key unavailable (`503 price_unavailable`), never free."""

    list_display = ["key", "credits", "label", "active", "updated_by", "updated_at"]
    list_filter = ["active"]
    search_fields = ["key", "label"]
    ordering = ["key", "-id"]

    def get_readonly_fields(self, request, obj=None):
        return ["key", "updated_by", "updated_at"] if obj else ["updated_by", "updated_at"]

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return obj is None or obj.active  # an old price is history: it can be read, not edited back to life

    def save_model(self, request, obj, form, change):
        now, who = SystemClock().now(), request.user.email
        if not change:
            obj.updated_by, obj.updated_at = who, now
            return super().save_model(request, obj, form, change)
        if not obj.active:
            PriceCatalog().deactivate(obj.key, by=who, now=now)
        else:
            PriceCatalog().revise(obj.key, obj.credits, by=who, now=now, label=obj.label)


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    """What can be bought. Prices and credits can be edited (a purchase keeps what it cost and a period what it
    grants, so an
    edit changes nothing already bought); a plan can be switched off but not added or deleted."""

    list_display = ["name", "key", "credits", "period_days", "price_paise", "max_quantity", "active", "sort"]
    list_editable = ["active"]
    ordering = ["sort"]

    def get_readonly_fields(self, request, obj=None):
        return ["key"] if obj else []

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PlanPurchase)
class PlanPurchaseAdmin(ReadOnlyAdmin):
    list_display = ["id", "user", "plan", "quantity", "credits", "amount_paise", "source", "status", "created_at"]
    list_filter = ["status", "source", "plan"]
    search_fields = ["user__email"]
    list_select_related = ["user", "plan"]


@admin.register(PlanPeriod)
class PlanPeriodAdmin(ReadOnlyAdmin):
    list_display = ["id", "user", "purchase", "position", "starts_at", "ends_at", "credits", "status"]
    list_filter = ["status"]
    search_fields = ["user__email"]
    list_select_related = ["user", "purchase__plan"]
