"""The console's sign-in screens: a learner's verification, the people waiting for a code, the abuse board and
the sign-up challenge's switch. Views parse and format; `console.services` decide, and every write is audited in
the same transaction as the change."""

from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.response import Response

from console.pagination import ConsoleCursorPagination
from console.serializers_auth import (
    AbuseReportSerializer,
    AuthSettingsInputSerializer,
    ChallengeStateSerializer,
    PendingSignupPageSerializer,
    PendingSignupRowSerializer,
    ReasonInputSerializer,
    SignupActionSerializer,
    SignupApprovedSerializer,
    VerificationPanelSerializer,
)
from console.services.abuse import AbuseBoard, ChallengeSwitch
from console.services.learner_verification import LearnerVerification
from console.services.signups import PendingSignups

from .base import CONSOLE_TAG, ConsoleListView, ConsoleView

REFUSED = OpenApiResponse(description="`already_verified`, `account_closed`, `account_erased` or `nothing_to_unlock`.")


class LearnerVerificationView(ConsoleView):
    @extend_schema(
        tags=CONSOLE_TAG,
        summary="A learner's sign-in verification",
        description=(
            "Why this person may be stuck: whether and how their email was verified, how they can sign in, the "
            "last five codes (created, expires, tries, used or cancelled; **never the code**), the last five "
            "emails sent to them, the lock and where the account was made from. Read-only."
        ),
        responses={200: VerificationPanelSerializer},
    )
    def get(self, request, learner_id):
        return Response(VerificationPanelSerializer(LearnerVerification(self.audit).panel(learner_id)).data)


class LearnerVerificationResendView(ConsoleView):
    @extend_schema(
        tags=CONSOLE_TAG,
        summary="Send a learner a new sign-in code",
        description=(
            "Queues a fresh code to the learner's own address (the old one is cancelled). Audited as "
            "`learner.verification_resent`. `409` for a verified, closed or erased account."
        ),
        request=None,
        responses={200: VerificationPanelSerializer, 409: REFUSED},
    )
    def post(self, request, learner_id):
        return Response(VerificationPanelSerializer(LearnerVerification(self.audit).resend(learner_id)).data)


class LearnerVerificationUnlockView(ConsoleView):
    @extend_schema(
        tags=CONSOLE_TAG,
        summary="Unlock a learner's email",
        description=(
            "Clears the lock on the email and cancels its live codes, so the next try starts clean. Audited as "
            "`learner.verification_unlocked`. `409 nothing_to_unlock` when it is not locked and has no live code."
        ),
        request=None,
        responses={200: VerificationPanelSerializer, 409: REFUSED},
    )
    def post(self, request, learner_id):
        return Response(VerificationPanelSerializer(LearnerVerification(self.audit).unlock(learner_id)).data)


class LearnerMarkVerifiedView(ConsoleView):
    @extend_schema(
        tags=CONSOLE_TAG,
        summary="Mark a learner's email verified",
        description=(
            "Verifies the account by hand (source `staff`) and gives the signup credits, once. **`reason` is "
            "required** (at least 10 characters) and is kept in the change log as "
            "`learner.verification_marked`. Confirm the person out of band first. `409` for a verified, closed "
            "or erased account."
        ),
        request=ReasonInputSerializer,
        responses={200: VerificationPanelSerializer, 409: REFUSED},
    )
    def post(self, request, learner_id):
        body = ReasonInputSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        panel = LearnerVerification(self.audit).mark_verified(learner_id, body.validated_data.get("reason", ""))
        return Response(VerificationPanelSerializer(panel).data)


class SignupListView(ConsoleListView):
    serializer_class = PendingSignupRowSerializer

    class Pagination(ConsoleCursorPagination):
        ordering = "-created_at"

    pagination_class = Pagination

    def get_queryset(self):
        return PendingSignups.queryset(self.request.query_params.get("q", ""))

    @extend_schema(
        tags=CONSOLE_TAG,
        summary="Waiting for a code",
        description=(
            "Sign-ups that are not accounts yet: the address, when it was made, how many tries its live code has "
            "left and whether the email is locked. Never a code or a password hash. Page with `cursor`."
        ),
        parameters=[OpenApiParameter("q", str, description="Search the email.")],
        responses={200: PendingSignupPageSerializer},
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class SignupResendView(ConsoleView):
    @extend_schema(
        tags=CONSOLE_TAG,
        summary="Send a waiting sign-up a new code",
        description=(
            "A new code to the address given at sign-up. **It works only in the browser that made the sign-up** (its "
            "ticket); a person who has lost it registers again. Audited as `signup.resend`."
        ),
        request=None,
        responses={200: SignupActionSerializer},
    )
    def post(self, request, signup_id):
        return Response(SignupActionSerializer(PendingSignups(self.audit).resend(signup_id)).data)


class SignupUnlockView(ConsoleView):
    @extend_schema(
        tags=CONSOLE_TAG,
        summary="Unlock a waiting sign-up's email",
        description=(
            "Clears the lock and cancels the live code (then send a new one). `409 not_locked` when neither applies."
        ),
        request=None,
        responses={200: SignupActionSerializer},
    )
    def post(self, request, signup_id):
        return Response(SignupActionSerializer(PendingSignups(self.audit).unlock(signup_id)).data)


class SignupApproveView(ConsoleView):
    @extend_schema(
        tags=CONSOLE_TAG,
        summary="Approve a waiting sign-up",
        description=(
            "Makes the account **with an unusable password** (the hash the person typed is never copied), verified by "
            "staff, and gives the signup credits once. The person signs in with Google, or chooses a password with "
            '"Forgot password". **`reason` is required** (at least 10 characters). **Confirm the person out of band '
            "first.** `409` for an expired sign-up or an email that has an account."
        ),
        request=ReasonInputSerializer,
        responses={200: SignupApprovedSerializer},
    )
    def post(self, request, signup_id):
        body = ReasonInputSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        result = PendingSignups(self.audit).approve(signup_id, body.validated_data.get("reason", ""))
        return Response(SignupApprovedSerializer(result).data)


class AbuseView(ConsoleView):
    @extend_schema(
        tags=CONSOLE_TAG,
        summary="The abuse board",
        description=(
            "Accounts made, codes sent, wrong codes, refused throwaway addresses and failed challenges per day "
            "for the last 14 days, the busiest client addresses and email domains of the last 24 hours (never an "
            "email), the emails locked now, the sign-ups waiting, and the state of the sign-up challenge. "
            "Read-only."
        ),
        responses={200: AbuseReportSerializer},
    )
    def get(self, request):
        return Response(AbuseReportSerializer(AbuseBoard().report()).data)


class AuthSettingsView(ConsoleView):
    @extend_schema(
        tags=CONSOLE_TAG,
        summary="The sign-up challenge's switch",
        description=(
            "Whether visitors must pass Cloudflare Turnstile to sign up or ask for a code, and whether its keys "
            "are set."
        ),
        responses={200: ChallengeStateSerializer},
    )
    def get(self, request):
        return Response(ChallengeStateSerializer(ChallengeSwitch.state()).data)

    @extend_schema(
        tags=CONSOLE_TAG,
        summary="Switch the sign-up challenge on or off",
        description=(
            "Audited as `auth_settings.update` (before and after). Off by default. **`409 "
            "captcha_not_configured`** when switching on without `TURNSTILE_SITE_KEY` and "
            "`TURNSTILE_SECRET_KEY`. No change writes no entry."
        ),
        request=AuthSettingsInputSerializer,
        responses={200: ChallengeStateSerializer},
    )
    def put(self, request):
        body = AuthSettingsInputSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        state = ChallengeSwitch(self.audit).set(body.validated_data["captcha_enabled"])
        return Response(ChallengeStateSerializer(state).data)
