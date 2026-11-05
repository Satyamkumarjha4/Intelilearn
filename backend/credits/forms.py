"""The administrator's form for giving or taking credits. The reason is required: it is kept on the ledger row, which is
the only record of why a learner's balance moved by hand."""

import uuid

from django import forms


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
