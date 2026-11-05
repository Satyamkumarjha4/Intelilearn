"""The shapes of the credits endpoints, for the API schema and for reading the request. The views build the answers
themselves (they are computed, not model fields)."""

from rest_framework import serializers

from lessons.metering import MeteredAction


class BucketSerializer(serializers.Serializer):
    source = serializers.CharField(
        help_text="signup, daily, weekly_streak, monthly_streak, purchase, subscription, admin_grant or refund."
    )
    remaining = serializers.IntegerField()
    expires_at = serializers.DateTimeField(allow_null=True, help_text="Empty: these credits never expire.")


class NextExpirySerializer(serializers.Serializer):
    at = serializers.DateTimeField()
    credits = serializers.IntegerField(help_text="What is left in the parcel that lapses first.")


class WalletSerializer(serializers.Serializer):
    balance = serializers.IntegerField(help_text="What can be spent now.")
    held = serializers.IntegerField(help_text="Set aside for work that has not finished; not part of the balance.")
    buckets = BucketSerializer(many=True, help_text="The credits that can be spent, in the order they will be.")
    next_expiry = NextExpirySerializer(allow_null=True)
    exempt = serializers.BooleanField(help_text="Work costs this learner nothing.")


class QuoteRequestSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=[a.value for a in MeteredAction])
    size = serializers.DictField(
        required=False,
        default=dict,
        help_text=(
            "The hints the action is asked with (entry, intent, origin, sheets, num_questions…). "
            "Unknown or malformed ones are refused."
        ),
    )


class PriceLineSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()
    credits = serializers.IntegerField()


class QuoteSerializer(serializers.Serializer):
    action = serializers.CharField()
    lines = PriceLineSerializer(many=True, help_text="What is due now.")
    due_now = serializers.IntegerField()
    later_lines = PriceLineSerializer(many=True)
    later = serializers.IntegerField(help_text="What follows (a lesson from a Quick check is paid in two stages).")
    total = serializers.IntegerField()
    exempt = serializers.BooleanField(help_text="The learner is not charged; the prices are still those shown.")


class SubjectSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["lesson", "quiz"])
    id = serializers.UUIDField()
    title = serializers.CharField()


class TransactionSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    kind = serializers.ChoiceField(
        choices=["earned", "bought", "reserved", "used", "returned", "expired", "adjusted", "taken_back"]
    )
    text = serializers.CharField(help_text="The row in a learner's words.")
    amount = serializers.IntegerField(help_text="The change in the balance: negative takes credits away.")
    balance_after = serializers.IntegerField()
    created_at = serializers.DateTimeField()
    subject = SubjectSerializer(allow_null=True)


class StreakDaySerializer(serializers.Serializer):
    date = serializers.DateField()
    state = serializers.ChoiceField(
        choices=["active", "repaired", "missed", "pending"],
        help_text="pending is today, not yet done.",
    )


class TodaySerializer(serializers.Serializer):
    date = serializers.DateField(help_text="The learner's own date.")
    done = serializers.BooleanField()


class NextBonusSerializer(serializers.Serializer):
    streak_day = serializers.IntegerField(help_text="The day of the streak of the next bonus (a multiple of 7).")
    credits = serializers.IntegerField(help_text="What it pays; a multiple of 28 pays the week and the month.")
    days_to_go = serializers.IntegerField()


class RepairOutlookSerializer(serializers.Serializer):
    available = serializers.BooleanField()
    day = serializers.DateField(allow_null=True, help_text="The day that would be repaired (yesterday).")
    reason = serializers.ChoiceField(choices=["nothing_to_repair", "repair_limit"], allow_null=True)
    cost = serializers.IntegerField()
    left_week = serializers.IntegerField(help_text="Repairs left in the last 7 days' allowance.")
    left_month = serializers.IntegerField(help_text="Repairs left in the last 28 days' allowance.")


class StreakSerializer(serializers.Serializer):
    current = serializers.IntegerField(help_text="Consecutive days ending today or yesterday; 0 once a day was missed.")
    longest = serializers.IntegerField()
    run_started_on = serializers.DateField(allow_null=True)
    alive = serializers.BooleanField()
    zone = serializers.CharField(help_text="The time zone the learner's day is counted in.")
    today = TodaySerializer()
    days = StreakDaySerializer(many=True, help_text="The last 28 days, oldest first; the last is today.")
    next_bonus = NextBonusSerializer()
    repair = RepairOutlookSerializer()


class RepairedStreakSerializer(serializers.Serializer):
    current = serializers.IntegerField()
    longest = serializers.IntegerField()
    run_started_on = serializers.DateField(allow_null=True)
    alive = serializers.BooleanField()


class RepairResponseSerializer(serializers.Serializer):
    day = serializers.DateField(help_text="The day that was repaired.")
    cost = serializers.IntegerField()
    bonus = serializers.IntegerField(help_text="Credits paid because the repair completed a streak bonus.")
    streak = RepairedStreakSerializer()
