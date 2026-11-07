"""Orders and the events that settle them (credits plan §7.3).

Money is integer paise and the currency is INR. A `PaymentOrder` is one attempt to pay for one `PlanPurchase`; it moves
`created` → `pending` → `paid` → `fulfilled`, or ends `failed` or `expired`. A refund does not change the state: it adds
to `refunded_paise` (and takes credits back), so a partial refund works. `PaymentEventLog` keeps only the normalised
fields of what a provider said, never the raw body, and is unique on (gateway, event id), which is what makes an event
take effect once.
"""

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class PaymentOrder(models.Model):
    class Status(models.TextChoices):
        CREATED = "created", "Created"
        PENDING = "pending", "Waiting for payment"
        PAID = "paid", "Paid"
        FULFILLED = "fulfilled", "Fulfilled"
        FAILED = "failed", "Failed"
        EXPIRED = "expired", "Expired"

    #: states in which the learner is still expected to pay
    OPEN = (Status.CREATED, Status.PENDING)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="payment_orders")
    purchase = models.OneToOneField("credits.PlanPurchase", on_delete=models.PROTECT, related_name="order")
    gateway = models.CharField(max_length=20)
    amount_paise = models.PositiveIntegerField()
    currency = models.CharField(max_length=3, default="INR")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.CREATED)
    provider_ref = models.CharField(max_length=200, blank=True, help_text="The provider's id for the checkout.")
    payment_ref = models.CharField(max_length=200, blank=True, help_text="The provider's id for the payment itself.")
    checkout = models.JSONField(default=dict, blank=True, help_text="What the browser needs to pay. Never a secret.")
    refunded_paise = models.PositiveIntegerField(default=0)
    failure_reason = models.CharField(max_length=200, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField()
    paid_at = models.DateTimeField(null=True, blank=True)
    fulfilled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["gateway", "provider_ref"],
                condition=~Q(provider_ref=""),
                name="payment_order_one_per_provider_ref",
            ),
            models.CheckConstraint(
                condition=Q(refunded_paise__lte=models.F("amount_paise")), name="payment_order_refund_within_amount"
            ),
        ]
        indexes = [models.Index(fields=["status", "created_at"], name="payment_order_status_idx")]

    def __str__(self):
        return f"{self.gateway} {self.amount_paise}p ({self.status})"


class PaymentEventLog(models.Model):
    class Outcome(models.TextChoices):
        APPLIED = "applied", "Applied"
        DUPLICATE = "duplicate", "Seen before"
        UNKNOWN_ORDER = "unknown_order", "No such order"
        AMOUNT_MISMATCH = "amount_mismatch", "Amount or currency did not match"
        IGNORED = "ignored", "Nothing to do"

    id = models.BigAutoField(primary_key=True)
    gateway = models.CharField(max_length=20)
    event_id = models.CharField(max_length=200)
    kind = models.CharField(max_length=20)
    order = models.ForeignKey(PaymentOrder, null=True, blank=True, on_delete=models.PROTECT, related_name="events")
    provider_ref = models.CharField(max_length=200, blank=True)
    amount_paise = models.PositiveIntegerField(default=0)
    currency = models.CharField(max_length=3, default="INR")
    outcome = models.CharField(max_length=20, choices=Outcome.choices)
    shortfall = models.PositiveIntegerField(default=0, help_text="Credits of a refund that were already spent.")
    received_at = models.DateTimeField()

    class Meta:
        ordering = ["-id"]
        constraints = [models.UniqueConstraint(fields=["gateway", "event_id"], name="payment_event_once")]

    def __str__(self):
        return f"{self.gateway}:{self.event_id} {self.kind} ({self.outcome})"


class RefundAttempt(models.Model):
    """One refund an administrator asked a provider for, under the token of the form that asked. The token is what makes
    a double click, or a resend of the form, refund once: (token, order) is unique, and it is the provider's idempotency
    key where the provider has one. Together the rows say how much has been asked for but not yet confirmed by the
    provider's refund event, so a second submission never asks for more than remains. A refund the provider says
    failed, or a person marks failed, no longer counts: its amount can be asked for again."""

    class State(models.TextChoices):
        PENDING = "pending", "Waiting for the provider"
        CONFIRMED = "confirmed", "Done"
        FAILED = "failed", "Failed"

    token = models.UUIDField()
    order = models.ForeignKey(PaymentOrder, on_delete=models.PROTECT, related_name="refund_attempts")
    amount_paise = models.PositiveIntegerField()
    refund_ref = models.CharField(max_length=200, blank=True, help_text="The provider's id for the refund.")
    state = models.CharField(max_length=10, choices=State.choices, default=State.PENDING)
    created_at = models.DateTimeField()
    resolved_at = models.DateTimeField(null=True, blank=True, help_text="When the provider (or a person) settled it.")

    class Meta:
        ordering = ["-id"]
        constraints = [models.UniqueConstraint(fields=["token", "order"], name="refund_attempt_once")]
        indexes = [models.Index(fields=["state", "created_at"], name="refund_attempt_state_idx")]

    def __str__(self):
        return f"{self.order_id} {self.amount_paise}p ({self.token})"
