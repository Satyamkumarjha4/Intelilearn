"""The administrator's form for giving or taking credits. The reason is required: it is kept on the ledger row, which is
the only record of why a learner's balance moved by hand."""

import uuid

from django import forms

from .models import CreditSettings, Plan
from .plans.desk import PurchaseDesk
from .plans.errors import InvalidPlanRequest
from .plans.pricing import PlanPricing


class AdjustCreditsForm(forms.Form):
    amount = forms.IntegerField(
        label="Credits",
        help_text="Positive gives credits (they never expire); negative takes them, earliest expiry first.",
    )
    reason = forms.CharField(
        label="Reason",
        max_length=500,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Required. It is kept with the movement.",
    )
    # Made when the page is drawn, so sending the form twice moves the credits once.
    token = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount == 0:
            raise forms.ValidationError("Enter a number other than zero.")
        return amount

    def clean_reason(self):
        reason = self.cleaned_data["reason"].strip()
        if not reason:
            raise forms.ValidationError("Say why the credits are being given or taken.")
        return reason


class GivePlanForm(forms.Form):
    """An administrator puts a plan on a wallet for nothing. The reason is required and kept; what may be given is
    what may be
    bought (the same rules, from the same plan table), so a gift can never be something a purchase could not."""

    plan = forms.ChoiceField(label="Plan")
    quantity = forms.IntegerField(
        label="Weeks (Weekly Pro only)", required=False, help_text="Leave empty for 1. The other plans are given once."
    )
    credits = forms.IntegerField(label="Credits (one-time credits only)", required=False)
    reason = forms.CharField(
        label="Reason", max_length=500, widget=forms.Textarea(attrs={"rows": 3}), help_text="Required. It is kept."
    )
    # Made when the page is drawn, so sending the form twice gives the plan once.
    token = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.plans = {p.key: p for p in Plan.objects.filter(active=True)}
        self.fields["plan"].choices = [(p.key, p.name) for p in self.plans.values()]

    def clean_reason(self):
        reason = self.cleaned_data["reason"].strip()
        if not reason:
            raise forms.ValidationError("Say why the plan is being given.")
        return reason

    def clean(self):
        data = super().clean()
        plan = self.plans.get(data.get("plan", ""))
        if plan is None:
            return data
        settings = CreditSettings.load()
        quantity = 1 if data.get("quantity") is None else data["quantity"]
        try:
            PlanPricing().price(
                PurchaseDesk.terms_of(plan), quantity=quantity, credits=data.get("credits"),
                minimum=settings.min_one_time_credits, maximum=settings.max_one_time_credits,
            )  # fmt: skip
        except InvalidPlanRequest as refused:
            raise forms.ValidationError(str(refused.detail)) from None
        data["quantity"] = quantity
        return data
