"""The shapes of the console's credit, wallet, payment and revenue endpoints (docs/reference/api.md, "Console").

The plan and the settings are serialized from their models, so what the console accepts is what the models' own
validators accept, and a field added to a model is editable here without a second list to keep.
"""

import uuid

from rest_framework import serializers

from credits.models import CreditSettings, Plan
from payments.models import PaymentOrder, RefundAttempt


class ConsolePlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = ["key", "name", "credits", "period_days", "price_paise", "max_quantity", "active", "sort"]
        read_only_fields = ["key"]


class CreditSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = CreditSettings
        exclude = ["id"]


class PriceHistorySerializer(serializers.Serializer):
    credits = serializers.IntegerField()
    label = serializers.CharField()
    active = serializers.BooleanField()
    updated_by = serializers.CharField(allow_blank=True)
    updated_at = serializers.DateTimeField()


class PriceSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()
    credits = serializers.IntegerField(
        allow_null=True, help_text="The live price, or null when the key has none (then it is unavailable, never free)."
    )
    available = serializers.BooleanField()
    updated_by = serializers.CharField(allow_blank=True)
    updated_at = serializers.DateTimeField()
    history = PriceHistorySerializer(
        many=True, help_text="Every price this key has had, newest first (the live one included)."
    )


class PriceInputSerializer(serializers.Serializer):
    credits = serializers.IntegerField(min_value=0, help_text="The new price. 0 is a price (free), not a missing one.")
    label = serializers.CharField(max_length=120, required=False, help_text="The words on the learner's quote line.")


class CreditsConfigSerializer(serializers.Serializer):
    prices = PriceSerializer(many=True)
    plans = ConsolePlanSerializer(many=True)
    settings = CreditSettingsSerializer()


class ConsoleBucketSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    source = serializers.CharField()
    remaining = serializers.IntegerField()
    granted = serializers.IntegerField()
    expires_at = serializers.DateTimeField(allow_null=True)
    lapsed = serializers.BooleanField(help_text="Past its expiry but not yet written off by the hourly job.")
    created_at = serializers.DateTimeField()


class LedgerRowSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    type = serializers.CharField()
    amount = serializers.IntegerField()
    balance_after = serializers.IntegerField()
    action = serializers.CharField(allow_blank=True)
    reason = serializers.CharField(allow_blank=True)
    created_at = serializers.DateTimeField()


class WalletLearnerSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField(allow_blank=True)
    email = serializers.EmailField()


class WalletPanelSerializer(serializers.Serializer):
    learner = WalletLearnerSerializer()
    balance = serializers.IntegerField(help_text="What the learner can spend now.")
    reserved = serializers.IntegerField(help_text="Set aside for work that has not finished.")
    credits_exempt = serializers.BooleanField()
    buckets = ConsoleBucketSerializer(many=True, help_text="Live credits, the ones that run out first listed first.")
    transactions = LedgerRowSerializer(many=True, help_text="The most recent 50 movements, newest first.")


class AdjustInputSerializer(serializers.Serializer):
    amount = serializers.IntegerField(
        help_text="Positive gives credits that never expire; negative takes them, earliest expiry first."
    )
    reason = serializers.CharField(
        max_length=500, trim_whitespace=True, help_text="Required. Kept on the ledger row and in the change log."
    )
    token = serializers.UUIDField(
        default=uuid.uuid4, help_text="Made when the form is drawn: sending it twice moves the credits once."
    )

    def validate_amount(self, amount):
        if amount == 0:
            raise serializers.ValidationError("Enter a number other than zero.")
        return amount


class ExemptInputSerializer(serializers.Serializer):
    credits_exempt = serializers.BooleanField()


class RefundAttemptSerializer(serializers.ModelSerializer):
    can_mark_failed = serializers.BooleanField(
        help_text="Only for a waiting refund whose provider cannot be asked about it."
    )

    class Meta:
        model = RefundAttempt
        fields = ["id", "amount_paise", "refund_ref", "state", "created_at", "resolved_at", "can_mark_failed"]


class PaymentLearnerSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField(allow_blank=True)
    email = serializers.EmailField()


class PaymentRowSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    learner = PaymentLearnerSerializer()
    gateway = serializers.CharField()
    plan = serializers.CharField()
    amount_paise = serializers.IntegerField()
    refunded_paise = serializers.IntegerField()
    currency = serializers.CharField()
    status = serializers.ChoiceField(
        choices=PaymentOrder.Status.choices, help_text="created, pending, paid, fulfilled, failed or expired."
    )
    provider_ref = serializers.CharField(allow_blank=True)
    payment_ref = serializers.CharField(allow_blank=True)
    created_at = serializers.DateTimeField()
    paid_at = serializers.DateTimeField(allow_null=True)
    shortfall_credits = serializers.IntegerField(help_text="Credits of refunds that were already spent, summed.")
    refunds = RefundAttemptSerializer(many=True, help_text="Every refund asked for, newest first.")


class PaymentsSummarySerializer(serializers.Serializer):
    shortfalls = serializers.IntegerField(help_text="Refund or dispute events whose credits were already spent.")
    refunds_waiting = serializers.IntegerField()
    orders_waiting = serializers.IntegerField()


class PaymentPageSerializer(serializers.Serializer):
    next = serializers.CharField(allow_null=True)
    previous = serializers.CharField(allow_null=True)
    results = PaymentRowSerializer(many=True)
    summary = PaymentsSummarySerializer()


class ShortfallSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    order = serializers.UUIDField(allow_null=True)
    learner = serializers.DictField(allow_null=True)
    gateway = serializers.CharField()
    kind = serializers.CharField()
    amount_paise = serializers.IntegerField()
    shortfall_credits = serializers.IntegerField()
    received_at = serializers.DateTimeField()


class RefundInputSerializer(serializers.Serializer):
    token = serializers.UUIDField(
        help_text="Made when the form is drawn: a token refunds once, however often it arrives."
    )
    amount = serializers.CharField(
        required=False, allow_blank=True, help_text="Rupees, like 12.50. Blank: all that remains."
    )


class RefundResultSerializer(serializers.Serializer):
    kind = serializers.CharField(help_text="asked, or duplicate (this form was already sent).")
    amount_paise = serializers.IntegerField()
    message = serializers.CharField()
    order = PaymentRowSerializer()


class PeriodRangeSerializer(serializers.Serializer):
    start = serializers.DateTimeField()
    end = serializers.DateTimeField()


class RevenueSerializer(serializers.Serializer):
    range = serializers.CharField()
    period = PeriodRangeSerializer()
    orders = serializers.IntegerField(help_text="Orders paid in the range.")
    paid = serializers.CharField(help_text="Rupees taken, as a decimal string.")
    refunded = serializers.CharField(help_text="Rupees taken back by refunds and disputes in the range.")
    net = serializers.CharField()
    model_cost_usd = serializers.CharField(help_text="What model calls cost in the range, in dollars as recorded.")
    model_cost = serializers.CharField(help_text="The same in rupees, at `usd_inr_rate`.")
    after_model_cost = serializers.CharField(help_text="Net revenue less model cost, in rupees.")
    usd_inr_rate = serializers.CharField(help_text="Rupees per dollar (`USD_INR_RATE`) used for `model_cost`.")
