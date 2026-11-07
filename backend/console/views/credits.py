from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from console.serializers_credits import (
    AdjustInputSerializer,
    ConsolePlanSerializer,
    CreditsConfigSerializer,
    CreditSettingsSerializer,
    ExemptInputSerializer,
    PriceInputSerializer,
    PriceSerializer,
    WalletPanelSerializer,
)
from console.services.credit_config import CreditConfig
from console.services.wallets import WalletPanel

from .base import CONSOLE_TAG, ConsoleView


class CreditsView(ConsoleView):
    @extend_schema(
        tags=CONSOLE_TAG,
        summary="Prices, plans and credit settings",
        description=(
            "Everything about what credits cost and how they are earned: each price with its history, the plans, "
            "and the credit settings (amounts and windows)."
        ),
        responses={200: CreditsConfigSerializer},
    )
    def get(self, request):
        config = CreditConfig(self.audit)
        body = {"prices": config.prices(), "plans": config.plans(), "settings": config.settings()}
        return Response(CreditsConfigSerializer(body).data)


class PriceView(ConsoleView):
    @extend_schema(
        tags=CONSOLE_TAG,
        summary="Change a price",
        description=(
            "Makes the new price the live one by adding a row; the old row is kept as history, and a reserve already "
            "placed is not affected (the next one uses the new price). Nothing is written when the price and label are "
            "as they were. `404` for a key that has never had a price."
        ),
        request=PriceInputSerializer,
        responses={200: PriceSerializer},
    )
    def patch(self, request, key):
        data = PriceInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        return Response(PriceSerializer(CreditConfig(self.audit).revise_price(key, **data.validated_data)).data)


class PlanView(ConsoleView):
    @extend_schema(
        tags=CONSOLE_TAG,
        summary="Change a plan",
        description=(
            "Any subset of the plan's fields (not its key), checked by the model's own rules. It changes what is "
            "bought next: a purchase already made keeps what it cost and what it grants."
        ),
        request=ConsolePlanSerializer,
        responses={200: ConsolePlanSerializer},
    )
    def patch(self, request, key):
        return Response(CreditConfig(self.audit).update_plan(key, ConsolePlanSerializer, request.data))


class CreditSettingsView(ConsoleView):
    @extend_schema(
        tags=CONSOLE_TAG,
        summary="Change the credit settings",
        description=(
            "Any subset of the amounts and windows, checked by the model's own rules. "
            "Nothing is saved if one is refused."
        ),
        request=CreditSettingsSerializer,
        responses={200: CreditSettingsSerializer},
    )
    def patch(self, request):
        return Response(CreditConfig(self.audit).update_settings(CreditSettingsSerializer, request.data))


class WalletView(ConsoleView):
    @extend_schema(
        tags=CONSOLE_TAG,
        summary="A learner's wallet",
        description="Balance, what is set aside, the live credits, the last 50 ledger rows and the exempt switch.",
        responses={200: WalletPanelSerializer},
    )
    def get(self, request, learner_id):
        return Response(WalletPanelSerializer(WalletPanel(self.audit).of(learner_id)).data)

    @extend_schema(
        tags=CONSOLE_TAG,
        summary="Switch a learner's exemption",
        description=(
            "`credits_exempt`: their work costs nothing, and every action is still recorded at 0 credits. Off by "
            "default; being staff does not exempt anyone. Written to the change log."
        ),
        request=ExemptInputSerializer,
        responses={200: WalletPanelSerializer},
    )
    def patch(self, request, learner_id):
        data = ExemptInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        return Response(
            WalletPanelSerializer(
                WalletPanel(self.audit).set_exempt(learner_id, data.validated_data["credits_exempt"])
            ).data
        )


class WalletAdjustView(ConsoleView):
    @extend_schema(
        tags=CONSOLE_TAG,
        summary="Give or take credits",
        description=(
            "A positive amount gives credits that never expire; a negative one takes them, earliest expiry first, and "
            "never more than the balance. **The reason is required**: it is kept on the ledger row and in the change "
            "log. The `token` makes sending the form twice move the credits once."
        ),
        request=AdjustInputSerializer,
        responses={200: WalletPanelSerializer},
    )
    def post(self, request, learner_id):
        data = AdjustInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        if not data.validated_data["reason"].strip():
            raise ValidationError({"reason": ["Say why the credits are being given or taken."]})
        return Response(WalletPanelSerializer(WalletPanel(self.audit).adjust(learner_id, **data.validated_data)).data)
