from rest_framework import serializers


class PublicTestimonialSerializer(serializers.Serializer):
    name = serializers.CharField()
    context = serializers.CharField(help_text='Who they are, for example "Class 12 student".')
    quote = serializers.CharField()
    rating = serializers.IntegerField(allow_null=True, help_text="Stars from 1 to 5, or null when they gave none.")


class PublicTestimonialsSerializer(serializers.Serializer):
    testimonials = PublicTestimonialSerializer(many=True)


class PublicPlanSerializer(serializers.Serializer):
    key = serializers.CharField()
    name = serializers.CharField()
    credits = serializers.IntegerField(help_text="Credits each period gives.")
    period_days = serializers.IntegerField()
    price_paise = serializers.IntegerField(help_text="In paise (100 paise = 1 rupee), tax included.")
    max_quantity = serializers.IntegerField(help_text="Most periods that can be bought at once.")
    price_paise_per_credit = serializers.FloatField(allow_null=True)
    about_lessons = serializers.IntegerField(allow_null=True, help_text="Whole full lessons the credits pay for.")


class PublicOneTimeSerializer(serializers.Serializer):
    price_paise_per_credit = serializers.IntegerField()
    min_credits = serializers.IntegerField()
    max_credits = serializers.IntegerField()
    valid_days = serializers.IntegerField()


class PublicRangeSerializer(serializers.Serializer):
    min = serializers.IntegerField()
    max = serializers.IntegerField()


class PublicPricingSerializer(serializers.Serializer):
    plans = PublicPlanSerializer(many=True)
    one_time = PublicOneTimeSerializer(allow_null=True)
    signup_credits = serializers.IntegerField()
    signup_about_lessons = serializers.IntegerField(allow_null=True)
    daily_credits = serializers.IntegerField()
    weekly_streak_bonus = serializers.IntegerField()
    monthly_streak_bonus = serializers.IntegerField(help_text="Extra, at every 28th day of a streak.")
    bonus_valid_days = serializers.IntegerField(help_text="How long daily and streak credits last.")
    quick_check_questions = serializers.IntegerField(help_text="How many questions a Quick check asks.")
    lesson_credits = serializers.IntegerField(allow_null=True, help_text="A full lesson with its Test. Null: no price.")
    retake_credits = serializers.IntegerField(allow_null=True)
    sheet_credits = PublicRangeSerializer(allow_null=True)
    quiz_credits = PublicRangeSerializer(allow_null=True)
