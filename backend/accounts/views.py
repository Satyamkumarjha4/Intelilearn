from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.models import update_last_login
from django.http import Http404
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_control
from django.views.decorators.csrf import ensure_csrf_cookie
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import APIException, AuthenticationFailed
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.settings import api_settings as jwt_settings
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from .authentication import CookieJWTAuthentication
from .cookies import AuthCookies
from .models import OutboundMail, User
from .options import ProfileOptions
from .serializers import (
    LoginSerializer,
    ProfileOptionsSerializer,
    ProfileSerializer,
    RegisterSerializer,
    ResendSerializer,
    UserSerializer,
    VerifySerializer,
)
from .throttling import AuthRateThrottle, CodeLimits, LoginAccountThrottle
from .verification.login import LoginVerification
from .verification.signup import SignupVerification
from .verification.ticket import SignupTicket

AUTH_TAG = ["auth"]


class _PublicAuthView(APIView):
    """Endpoints that work without a valid access token but still require the CSRF header,
    because they read or set auth cookies."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        CookieJWTAuthentication().enforce_csrf(request)

    def get_authenticate_header(self, request):
        # Without an authenticator DRF would turn AuthenticationFailed into 403; keep it a 401.
        return 'Bearer realm="api"'

    @staticmethod
    def client_address(request) -> str | None:
        """The visitor's address as the throttles count it (`TRUSTED_PROXY_COUNT`), or None when there is none."""
        return BaseThrottle().get_ident(request) or None

    def signed_in_response(self, user, status_code=status.HTTP_200_OK) -> Response:
        """The user, with fresh tokens set as cookies (verify and login)."""
        refresh = RefreshToken.for_user(user)
        response = Response({"user": UserSerializer(user).data}, status=status_code)
        AuthCookies().set_session(
            response, access=str(refresh.access_token), refresh=str(refresh), onboarded=user.profile.is_complete
        )
        return response


_user_envelope = {"type": "object", "properties": {"user": {"$ref": "#/components/schemas/User"}}}
_verification_envelope = {
    "type": "object",
    "properties": {"status": {"type": "string", "enum": ["verification_required"]}},
}
_sent_envelope = {"type": "object", "properties": {"status": {"type": "string", "enum": ["sent"]}}}


@method_decorator(ensure_csrf_cookie, name="dispatch")
class CsrfView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(
        tags=AUTH_TAG,
        summary="Set the CSRF cookie",
        description="Sets `csrftoken`. Send its value as `X-CSRFToken` on every POST/PUT/PATCH/DELETE.",
        responses={204: None},
    )
    def get(self, request):
        return Response(status=status.HTTP_204_NO_CONTENT)


class InvalidCode(APIException):
    """The one answer to every failed code check (plan T9): a wrong code, an expired one, a used one, a dead one, a
    locked email, an email nobody asked a code for and a missing or stale signup ticket all say exactly this."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "invalid_code"
    default_detail = "That code didn't work. Check it, or ask for a new one."


class VerificationRequired(APIException):
    """The password was right but the email was never proved: a code was sent, and the next step is to enter it."""

    status_code = status.HTTP_403_FORBIDDEN
    default_code = "verification_required"
    default_detail = "Check your email: we sent you a code to finish signing in."


class RegisterView(_PublicAuthView):
    throttle_classes = [AuthRateThrottle]
    throttle_scope = "auth"

    @extend_schema(
        tags=AUTH_TAG,
        summary="Start creating an account: a code is emailed",
        description=(
            "Keeps a pending sign-up and emails a 6-digit code. **No account, no session and no credits yet.** The "
            "reply is the same for an address that has an account (its owner is told by email instead) and sets the "
            "`lc_signup` ticket cookie, which `/auth/verify` needs."
        ),
        request=RegisterSerializer,
        responses={202: OpenApiResponse(_verification_envelope, description="A code was emailed (or its owner told)")},
    )
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        signup = serializer.signup_request()
        CodeLimits().enforce(request, self, signup.email, CodeLimits.SEND)
        started = SignupVerification().start(signup, ip=self.client_address(request))
        response = Response({"status": "verification_required"}, status=status.HTTP_202_ACCEPTED)
        AuthCookies().set_signup_ticket(response, started.ticket, SignupTicket().settings.ticket_ttl)
        return response


class VerifyView(_PublicAuthView):
    throttle_classes = [AuthRateThrottle]
    throttle_scope = "auth"

    @extend_schema(
        tags=AUTH_TAG,
        summary="Enter the emailed code",
        description=(
            "`purpose: signup` creates the account (the `lc_signup` cookie from `/auth/register` must come with it); "
            "`purpose: login` verifies an existing account that signed in with the right password. Every failure is "
            "`400 invalid_code`."
        ),
        request=VerifySerializer,
        responses={200: OpenApiResponse(_user_envelope, description="Signed in; auth cookies set"), 400: None},
    )
    def post(self, request):
        serializer = VerifySerializer(data=request.data)
        if not serializer.is_valid():
            raise InvalidCode()
        email, code, purpose = (serializer.validated_data[key] for key in ("email", "code", "purpose"))
        CodeLimits().enforce(request, self, email, CodeLimits.CHECK)
        if purpose == "signup":
            ticket = request.COOKIES.get(SignupTicket.COOKIE)
            user = SignupVerification().confirm(email, code, ticket, ip=self.client_address(request))
        else:
            user = LoginVerification().confirm(email, code)
        if user is None:
            raise InvalidCode()
        update_last_login(None, user)
        response = self.signed_in_response(user)
        AuthCookies().clear_signup_ticket(response)
        return response


class VerifyResendView(_PublicAuthView):
    throttle_classes = [AuthRateThrottle]
    throttle_scope = "auth"

    @extend_schema(
        tags=AUTH_TAG,
        summary="Send a new code",
        description=(
            "Always `202`. A `signup` resend needs the `lc_signup` cookie and sends nothing without it; a `login` "
            "resend sends only to an unverified account. A `429` carries `Retry-After`."
        ),
        request=ResendSerializer,
        responses={202: OpenApiResponse(_sent_envelope), 429: None},
    )
    def post(self, request):
        serializer = ResendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email, purpose = serializer.validated_data["email"], serializer.validated_data["purpose"]
        CodeLimits().enforce(request, self, email, CodeLimits.SEND)
        ip = self.client_address(request)
        if purpose == "signup":
            SignupVerification().resend(email, request.COOKIES.get(SignupTicket.COOKIE), ip=ip)
        else:
            LoginVerification().resend(email, ip=ip)
        return Response({"status": "sent"}, status=status.HTTP_202_ACCEPTED)


class LoginView(_PublicAuthView):
    throttle_classes = [AuthRateThrottle, LoginAccountThrottle]
    throttle_scope = "auth"

    @extend_schema(
        tags=AUTH_TAG,
        summary="Sign in",
        request=LoginSerializer,
        responses={
            200: OpenApiResponse(_user_envelope, description="Signed in; auth cookies set"),
            401: None,
            403: OpenApiResponse(description="`verification_required`: the email was never proved; a code was sent"),
        },
    )
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = authenticate(
            request, email=serializer.validated_data["email"], password=serializer.validated_data["password"]
        )
        if user is None:
            raise AuthenticationFailed("Invalid email or password.", code="invalid_credentials")
        if not user.is_email_verified:
            # Only a right password gets here. If the limits say no, the answer is the same and no code goes out.
            if CodeLimits().allows(request, self, user.email, CodeLimits.SEND):
                LoginVerification().start(user, ip=self.client_address(request))
            raise VerificationRequired()
        update_last_login(None, user)
        return self.signed_in_response(user)


class DevOutboxView(APIView):
    """The throwaway test stack's window on the mail log: a browser test reads its code here (plan T17, D5). It answers
    `404` everywhere else, and the system checks refuse the outbox backend in production."""

    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(exclude=True)
    def get(self, request):
        if not (settings.DEBUG and settings.MAIL_ALLOW_OUTBOX and settings.MAIL_BACKEND == "outbox"):
            raise Http404
        address = str(request.query_params.get("email", "")).strip()
        rows = OutboundMail.objects.filter(to_email__iexact=address).order_by("-created_at", "-pk")[:10]
        messages = [
            {"kind": row.kind, "to": row.to_email, "status": row.status, "subject": row.subject, "text": row.body_text}
            for row in rows
        ]
        return Response({"messages": messages})


class RefreshView(_PublicAuthView):
    # Its own budget: the app refreshes routinely, which must not eat into the login limit.
    throttle_classes = [AuthRateThrottle]
    throttle_scope = "auth_refresh"

    @extend_schema(
        tags=AUTH_TAG,
        summary="Renew the access token",
        description="Uses the `lc_refresh` cookie. The refresh token is rotated and the old one blacklisted.",
        request=None,
        responses={200: OpenApiResponse(_user_envelope), 401: None},
    )
    def post(self, request):
        user = None
        if raw_refresh := request.COOKIES.get(AuthCookies.REFRESH):
            serializer = TokenRefreshSerializer(data={"refresh": raw_refresh})
            try:
                serializer.is_valid(raise_exception=True)
                tokens = serializer.validated_data
                user_id = AccessToken(tokens["access"])[jwt_settings.USER_ID_CLAIM]
                user = User.objects.select_related("profile").filter(pk=user_id, is_active=True).first()
            except (TokenError, InvalidToken, AuthenticationFailed):  # expired, blacklisted, or user deactivated
                user = None
        if user is None:
            response = Response(
                {"detail": "Session expired. Please sign in again.", "code": "session_expired"},
                status=status.HTTP_401_UNAUTHORIZED,
            )
            AuthCookies().clear(response)
            return response

        response = Response({"user": UserSerializer(user).data})
        AuthCookies().set_session(
            response,
            access=tokens["access"],
            refresh=tokens.get("refresh", raw_refresh),
            onboarded=user.profile.is_complete,
        )
        return response


class LogoutView(_PublicAuthView):
    @extend_schema(tags=AUTH_TAG, summary="Sign out", request=None, responses={204: None})
    def post(self, request):
        token = request.COOKIES.get(AuthCookies.REFRESH)
        if token:
            try:
                RefreshToken(token).blacklist()
            except TokenError:
                pass  # already expired or blacklisted: signing out still succeeds
        response = Response(status=status.HTTP_204_NO_CONTENT)
        AuthCookies().clear(response)
        return response


class MeView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = UserSerializer

    @extend_schema(tags=AUTH_TAG, summary="The signed-in user")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_object(self):
        return self.request.user


class ProfileView(generics.RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ProfileSerializer

    def get_object(self):
        return self.request.user.profile

    @extend_schema(tags=["profile"], summary="Get your profile")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(tags=["profile"], summary="Replace your profile (onboarding)")
    def put(self, request, *args, **kwargs):
        return self._update_and_mark(super().put(request, *args, **kwargs))

    @extend_schema(tags=["profile"], summary="Update part of your profile")
    def patch(self, request, *args, **kwargs):
        return self._update_and_mark(super().patch(request, *args, **kwargs))

    def _update_and_mark(self, response):
        AuthCookies().set_onboarded(response, response.data["profile_complete"])
        return response


class ProfileOptionsView(APIView):
    """The choice lists the profile accepts. Public: the sign-up screens read them before there is an account."""

    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["profile"],
        summary="The choices a profile accepts",
        description=(
            "Every choice list of the profile (`education_level`, `learning_preference`, `goal`, "
            "`preferred_language`) as `{value, label}` in display order. No sign-in needed."
        ),
        responses={200: ProfileOptionsSerializer},
    )
    @method_decorator(cache_control(public=True, max_age=3600))
    def get(self, request):
        return Response(ProfileOptions().payload())
