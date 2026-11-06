"""The credit ledger's tables (docs/to_be_developed/credits-implementation-plan.md §7.2).

Money is an integer here: credits as whole numbers, never a float or a Decimal (T3). Nothing in this module reads the
clock: every timestamp is given by the caller (`Ledger` takes it from its `Clock`), so a test controls them all.
Rows that must outlive the things they are about hold plain columns (`subject_kind`, `subject_id`, `purchase_id`), not
foreign keys, so deleting a lesson never touches money (K2). The user is a protected foreign key: an account with a
wallet cannot be deleted until someone decides what happens to its ledger, which is append-only.
"""

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q

from .errors import AppendOnly


class Wallet(models.Model):
    """One row per learner: the lock every movement of that learner's credits takes first (K1), so two movements for
    one learner never interleave, and a learner with no credits yet still has something to lock."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, primary_key=True, related_name="wallet"
    )
    credits_exempt = models.BooleanField(
        default=False, help_text="Work costs this learner nothing; every action is still recorded at 0 credits."
    )
    created_at = models.DateTimeField()

    def __str__(self):
        return f"Wallet of {self.user}"


class CreditBucket(models.Model):
    """A parcel of credits with one source and one expiry. Spending takes from the buckets that expire first."""

    class Source(models.TextChoices):
        SIGNUP = "signup", "Signup"
        DAILY = "daily", "Daily activity"
        WEEKLY_STREAK = "weekly_streak", "Weekly streak"
        MONTHLY_STREAK = "monthly_streak", "Monthly streak"
        PURCHASE = "purchase", "Purchase"
        SUBSCRIPTION = "subscription", "Subscription"
        ADMIN_GRANT = "admin_grant", "Admin grant"
        REFUND = "refund", "Given back after a failure"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="credit_buckets")
    source = models.CharField(max_length=20, choices=Source.choices)
    amount_granted = models.PositiveIntegerField()
    amount_remaining = models.PositiveIntegerField()
    expires_at = models.DateTimeField(null=True, blank=True, help_text="Empty: never.")
    purchase_id = models.UUIDField(
        null=True, blank=True, help_text="The plan purchase these credits were bought with (a plain column; see K2)."
    )
    revoked_at = models.DateTimeField(
        null=True, blank=True, help_text="Set when a refund took these credits back: a late release will not refill it."
    )
    created_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(amount_granted__gt=0) & Q(amount_remaining__lte=F("amount_granted")),
                name="credit_bucket_remaining_within_granted",
            ),
        ]
        indexes = [
            models.Index(
                fields=["user", "expires_at"],
                condition=Q(amount_remaining__gt=0),
                name="credit_bucket_spendable_idx",
            ),
            models.Index(
                fields=["purchase_id"], condition=Q(purchase_id__isnull=False), name="credit_bucket_purchase_idx"
            ),
        ]

    def __str__(self):
        return f"{self.source} {self.amount_remaining}/{self.amount_granted}"


class AppendOnlyQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise AppendOnly("Ledger rows cannot be changed.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise AppendOnly("Ledger rows cannot be changed.")

    def delete(self):
        raise AppendOnly("Ledger rows cannot be deleted.")


class CreditHold(models.Model):
    """Credits reserved for one authorized action. Its id is the authorization's id. It takes the credits out of the
    buckets at once and records where from, so a release can put them back where they came from (T6, T7)."""

    class Status(models.TextChoices):
        HELD = "held", "Held"
        COMMITTED = "committed", "Committed"
        RELEASED = "released", "Released"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="credit_holds")
    action = models.CharField(max_length=40)
    subject_kind = models.CharField(max_length=20, blank=True)
    subject_id = models.UUIDField(null=True, blank=True)
    amount = models.PositiveIntegerField()
    lines = models.JSONField(default=list, help_text="What was charged, line by line (written by the gate).")
    allocations = models.JSONField(default=list, help_text="[{bucket, amount}] the credits were taken from.")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.HELD)
    exempt = models.BooleanField(default=False)
    idempotency_key = models.CharField(max_length=200, unique=True)
    orphan_deadline = models.DateTimeField(
        null=True, blank=True, help_text="If no run has claimed the hold by then, it is released."
    )
    created_at = models.DateTimeField()
    settled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["action", "subject_id"],
                condition=Q(status="held"),
                name="credit_hold_one_held_per_action_and_subject",
            ),
        ]
        indexes = [models.Index(fields=["status", "created_at"], name="credit_hold_status_idx")]

    def __str__(self):
        return f"{self.action} {self.amount} ({self.status})"


class CreditTransaction(models.Model):
    """One immutable row of the ledger. `amount` is the change in the learner's balance (a hold is negative, a release
    positive, a commit zero); `balance_after` is the running total, so the sum of a learner's amounts is always the
    sum of
    their buckets (T4)."""

    class Type(models.TextChoices):
        GRANT = "grant", "Grant"
        DEBIT = "debit", "Debit"
        HOLD = "hold", "Hold"
        COMMIT = "commit", "Commit"
        RELEASE = "release", "Release"
        REFUND = "refund", "Refund"
        REPAIR = "repair", "Streak repair"
        ADMIN_ADJUST = "admin_adjust", "Admin adjustment"
        EXPIRE = "expire", "Expiry"
        FORFEIT = "forfeit", "Forfeit (account closed)"

    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="credit_transactions")
    type = models.CharField(max_length=20, choices=Type.choices)
    amount = models.IntegerField(help_text="The change in the balance: negative takes credits away.")
    balance_after = models.PositiveIntegerField()
    action = models.CharField(max_length=40, blank=True)
    subject_kind = models.CharField(max_length=20, blank=True)
    subject_id = models.UUIDField(null=True, blank=True)
    hold = models.ForeignKey(CreditHold, null=True, blank=True, on_delete=models.PROTECT, related_name="transactions")
    bucket_allocations = models.JSONField(default=list)
    idempotency_key = models.CharField(max_length=200, unique=True)
    meta = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField()

    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        ordering = ["-id"]
        indexes = [models.Index(fields=["user", "-id"], name="credit_tx_user_idx")]

    def __str__(self):
        return f"{self.type} {self.amount:+d} for {self.user_id}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise AppendOnly("Ledger rows cannot be changed.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise AppendOnly("Ledger rows cannot be deleted.")


class Plan(models.Model):
    """What can be bought (docs/to_be_developed/credits-implementation-plan.md §7.2, D1): one-time credits at a price
    a credit,
    and three plans that give credits for a period. Edited in the admin. A purchase stores what it cost, and a period
    what it
    grants, so an edit never changes what was already bought."""

    class Key(models.TextChoices):
        ONE_TIME = "one_time", "One-time credits"
        WEEKLY_PRO = "weekly_pro", "Weekly Pro"
        MONTHLY_PRO = "monthly_pro", "Monthly Pro"
        PRO_PLUS = "pro_plus", "Pro Plus"

    key = models.CharField(max_length=20, choices=Key.choices, unique=True)
    name = models.CharField(max_length=60)
    credits = models.PositiveIntegerField(
        help_text="Credits each period gives. 0 for one-time credits (the buyer chooses)."
    )
    period_days = models.PositiveIntegerField(
        help_text="How long a period lasts; for one-time credits, how long they last."
    )
    price_paise = models.PositiveIntegerField(
        help_text="In paise (100 paise = 1 rupee), tax included. For one-time credits, the price of one credit."
    )
    max_quantity = models.PositiveSmallIntegerField(default=1, help_text="Most that can be bought at once.")
    active = models.BooleanField(default=True, help_text="Off: not offered. Purchases already made are not affected.")
    sort = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort", "id"]

    def __str__(self):
        return self.name

    @property
    def is_one_time(self) -> bool:
        return self.key == self.Key.ONE_TIME


class PlanPurchase(models.Model):
    """Someone bought, or was given, a plan. Opened `pending` with the amount the server computed (never the
    client's), and
    `fulfilled` once, by `PlanFulfilment`, which is where its credits come from. An administrator's gift is marked
    (`source` admin), costs nothing, and keeps who gave it and why in `meta`."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        FULFILLED = "fulfilled", "Fulfilled"
        VOID = "void", "Void"

    class Source(models.TextChoices):
        PAYMENT = "payment", "Payment"
        ADMIN = "admin", "Given by an administrator"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="plan_purchases")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="purchases")
    quantity = models.PositiveSmallIntegerField(default=1, help_text="Weeks of Weekly Pro; 1 for the rest.")
    credits = models.PositiveIntegerField(default=0, help_text="The one-time amount bought; 0 for a plan.")
    amount_paise = models.PositiveIntegerField(help_text="What it cost, in paise. 0 for a gift.")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.PAYMENT)
    meta = models.JSONField(default=dict, blank=True, help_text="For a gift: reason, by, list_amount_paise.")
    created_at = models.DateTimeField()
    fulfilled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.CheckConstraint(condition=Q(quantity__gte=1), name="plan_purchase_quantity_at_least_one")]
        indexes = [models.Index(fields=["user", "status"], name="plan_purchase_user_idx")]

    def __str__(self):
        return f"{self.plan.name} x{self.quantity} ({self.status})"


class PlanPeriod(models.Model):
    """One period of a plan: it grants its credits when it starts, not before, and they last until it ends. Periods
    of one
    learner never overlap; a purchase of several weeks makes several."""

    class Status(models.TextChoices):
        QUEUED = "queued", "Waiting"
        ACTIVE = "active", "Running"
        ENDED = "ended", "Ended"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="plan_periods")
    purchase = models.ForeignKey(PlanPurchase, on_delete=models.PROTECT, related_name="periods")
    position = models.PositiveSmallIntegerField(help_text="1 for the first week of a purchase.")
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    credits = models.PositiveIntegerField()
    bucket = models.OneToOneField(
        "CreditBucket", null=True, blank=True, on_delete=models.PROTECT, related_name="period",
        help_text="Made when the period starts; empty while it waits.",
    )  # fmt: skip
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.QUEUED)

    class Meta:
        ordering = ["starts_at", "position"]
        constraints = [models.UniqueConstraint(fields=["purchase", "position"], name="plan_period_one_per_position")]
        indexes = [models.Index(fields=["user", "starts_at"], name="plan_period_user_idx")]

    def __str__(self):
        return f"{self.purchase.plan.name} {self.starts_at:%Y-%m-%d} ({self.status})"


class StreakDay(models.Model):
    """A day the learner counts as active, in their own time zone. The days are the truth about a streak;
    `StreakState` is
    only a cache of what they add up to. A repaired day keeps the streak alive but earned no daily credit."""

    class Kind(models.TextChoices):
        ACTIVE = "active", "Active"
        REPAIRED = "repaired", "Repaired"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="streak_days")
    local_date = models.DateField()
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.ACTIVE)
    repaired_on = models.DateField(
        null=True, blank=True, help_text="The local day the repair was made; the limits count it."
    )
    created_at = models.DateTimeField()

    class Meta:
        ordering = ["user", "local_date"]
        constraints = [
            models.UniqueConstraint(fields=["user", "local_date"], name="streak_day_one_per_user_and_date"),
            models.CheckConstraint(
                condition=Q(kind="active", repaired_on__isnull=True) | Q(kind="repaired", repaired_on__isnull=False),
                name="streak_day_repaired_on_only_when_repaired",
            ),
        ]
        indexes = [models.Index(fields=["user", "repaired_on"], name="streak_day_repairs_idx")]

    def __str__(self):
        return f"{self.local_date} ({self.kind})"


class StreakState(models.Model):
    """What a learner's days add up to, kept for reading without adding them up. A cache: it can be rebuilt from the
    `StreakDay`s at any time, and nothing decides anything from it."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, primary_key=True, related_name="streak_state"
    )
    current_streak = models.PositiveIntegerField(default=0)
    longest_streak = models.PositiveIntegerField(default=0)
    run_started_on = models.DateField(null=True, blank=True)
    last_day = models.DateField(null=True, blank=True)
    updated_at = models.DateTimeField()

    def __str__(self):
        return f"{self.current_streak} (longest {self.longest_streak})"


class ActionPrice(models.Model):
    """What something costs, in credits (docs/to_be_developed/credits-implementation-plan.md T10, K8). Prices are
    versioned:
    changing one adds a row and switches the old row off (`PriceCatalog.revise`), so there is one live row for a key
    and the
    old ones are the history. A key with no live row is unavailable, never free. `credits` may be 0: that is a price."""

    key = models.CharField(max_length=60)
    credits = models.PositiveIntegerField()
    label = models.CharField(max_length=120, help_text="In the learner's words: it is a line of the quote.")
    active = models.BooleanField(default=True)
    updated_by = models.CharField(max_length=254, blank=True)
    updated_at = models.DateTimeField()

    class Meta:
        ordering = ["key", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["key"], condition=Q(active=True), name="action_price_one_live_per_key"),
        ]

    def __str__(self):
        return f"{self.key} = {self.credits}" + ("" if self.active else " (old)")

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self._forget()

    def delete(self, *args, **kwargs):
        result = super().delete(*args, **kwargs)
        self._forget()
        return result

    @staticmethod
    def _forget():
        """The book is cached: a saved price must show at once, and again once the transaction is over."""
        from django.db import transaction

        from .pricing.book import PriceBook

        PriceBook.clear()
        transaction.on_commit(PriceBook.clear)


class CreditSettings(models.Model):
    """Singleton: every amount and window the credits rules use, edited in the admin (and later the console) the way
    `FlowSettings` is (T18). The defaults are the spec's."""

    # --- what is earned
    signup_credits = models.PositiveIntegerField(
        default=30, help_text="Given once when an account is ready. Never expire."
    )
    daily_credits = models.PositiveIntegerField(default=1, help_text="For each day with real study.")
    weekly_streak_bonus = models.PositiveIntegerField(default=10, help_text="At every 7th day of a streak.")
    monthly_streak_bonus = models.PositiveIntegerField(default=10, help_text="Extra, at every 28th day of a streak.")
    # --- how long credits last
    bonus_valid_days = models.PositiveIntegerField(default=90, help_text="Daily and streak credits.")
    purchased_valid_days = models.PositiveIntegerField(default=365, help_text="One-time purchases.")
    refund_valid_days = models.PositiveIntegerField(
        default=30, help_text="Credits given back after a failure, when their first bucket has run out."
    )
    # --- streak repair
    repair_cost = models.PositiveIntegerField(default=1)
    repair_window_hours = models.PositiveIntegerField(default=48, help_text="A missed day can be repaired within this.")
    repair_limit_week = models.PositiveIntegerField(default=1, help_text="Repairs in any 7 days.")
    repair_limit_month = models.PositiveIntegerField(default=3, help_text="Repairs in any 28 days.")
    # --- when a learner is told credits are about to run out
    weekly_notice_days = models.PositiveIntegerField(default=2)
    monthly_notice_days = models.PositiveIntegerField(default=7)
    bonus_notice_days = models.PositiveIntegerField(default=7)
    purchased_notice_days = models.PositiveIntegerField(default=30, help_text="First notice, shown for 3 days.")
    purchased_notice_show_days = models.PositiveIntegerField(default=3)
    purchased_final_notice_days = models.PositiveIntegerField(default=7)
    # --- buying
    min_one_time_credits = models.PositiveIntegerField(default=10, validators=[MinValueValidator(1)])
    max_one_time_credits = models.PositiveIntegerField(default=5000, validators=[MinValueValidator(1)])
    paise_per_credit = models.PositiveIntegerField(default=100, validators=[MinValueValidator(1)])
    max_queued_periods = models.PositiveIntegerField(
        default=12, validators=[MinValueValidator(1), MaxValueValidator(60)], help_text="Plan periods lined up at once."
    )
    max_pending_orders = models.PositiveIntegerField(default=3, validators=[MinValueValidator(1)])
    # --- housekeeping
    orphan_minutes = models.PositiveIntegerField(
        default=30,
        validators=[MinValueValidator(1)],
        help_text="A hold that no run claimed in this long is released. A paused run's hold is never released by age.",
    )

    class Meta:
        verbose_name = verbose_name_plural = "credit settings"

    def __str__(self):
        return "Credit settings"

    def save(self, *args, **kwargs):
        self.pk = 1  # singleton
        super().save(*args, **kwargs)

    def clean(self):
        if self.min_one_time_credits is not None and self.max_one_time_credits is not None:
            if self.min_one_time_credits > self.max_one_time_credits:
                raise ValidationError({"min_one_time_credits": "The smallest purchase cannot exceed the largest."})

    @classmethod
    def load(cls) -> "CreditSettings":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
