"""The shapes of the payments endpoints, for the API schema and for reading the request."""

from rest_framework import serializers


class GatewayChoiceSerializer(serializers.Serializer):
    key = serializers.CharField()
    display_name = serializers.CharField()


class GatewaysSerializer(serializers.Serializer):
    gateways = GatewayChoiceSerializer(many=True, help_text="The ways to pay that are switched on; empty when none is.")
    default = serializers.CharField(allow_null=True, help_text="The one to use when the learner is not asked.")


class OrderRequestSerializer(serializers.Serializer):
    plan = serializers.CharField(help_text="`one_time`, `weekly_pro`, `monthly_pro` or `pro_plus`.")
    quantity = serializers.IntegerField(required=False, min_value=1, default=1, help_text="Weeks of Weekly Pro.")
    credits = serializers.IntegerField(required=False, min_value=1, help_text="For `one_time`: how many credits.")
    gateway = serializers.CharField(required=False, help_text="One of the enabled gateways; the default when omitted.")


class CheckoutSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["redirect", "client"])
    redirect_url = serializers.CharField(required=False, help_text="For `redirect`: where to send the browser.")
    adapter = serializers.CharField(required=False, help_text="For `client`: which on-page checkout opens it.")
    client = serializers.DictField(required=False, help_text="For `client`: non-secret parameters for that checkout.")


class OrderPlanSerializer(serializers.Serializer):
    key = serializers.CharField()
    name = serializers.CharField()


class OrderSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    status = serializers.CharField(help_text="created, pending, paid, fulfilled, failed or expired.")
    gateway = serializers.CharField()
    plan = OrderPlanSerializer()
    quantity = serializers.IntegerField()
    credits = serializers.IntegerField(help_text="What the order gives: credits bought, or a plan's credits in all.")
    amount_paise = serializers.IntegerField(help_text="Paise, tax included.")
    currency = serializers.CharField()
    refunded_paise = serializers.IntegerField()
    created_at = serializers.DateTimeField()
    fulfilled_at = serializers.DateTimeField(allow_null=True)


class CreatedOrderSerializer(OrderSerializer):
    checkout = CheckoutSerializer(help_text="How the browser pays.")


class OrdersSerializer(serializers.Serializer):
    orders = OrderSerializer(many=True)


class WebhookReceivedSerializer(serializers.Serializer):
    received = serializers.IntegerField(help_text="How many events the callback carried.")
