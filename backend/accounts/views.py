from django.contrib.auth import authenticate
from django.contrib.auth.models import update_last_login
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.settings import api_settings as jwt_settings
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from .authentication import CookieJWTAuthentication
from .cookies import AuthCookies
from .models import User
from .serializers import LoginSerializer, ProfileSerializer, RegisterSerializer, UserSerializer
from .throttling import AuthRateThrottle, LoginAccountThrottle

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

    def signed_in_response(self, user, status_code=status.HTTP_200_OK) -> Response:
        """The user, with fresh tokens set as cookies (register and login)."""
        refresh = RefreshToken.for_user(user)
        response = Response({"user": UserSerializer(user).data}, status=status_code)
        AuthCookies().set_session(
            response, access=str(refresh.access_token), refresh=str(refresh), onboarded=user.profile.is_complete
        )
        return response


_user_envelope = {"type": "object", "properties": {"user": {"$ref": "#/components/schemas/User"}}}


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


class RegisterView(_PublicAuthView):
    throttle_classes = [AuthRateThrottle]
    throttle_scope = "auth"

    @extend_schema(
        tags=AUTH_TAG,
        summary="Create an account and sign in",
        request=RegisterSerializer,
        responses={201: OpenApiResponse(_user_envelope, description="Signed in; auth cookies set")},
    )
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        update_last_login(None, user)
        return self.signed_in_response(user, status.HTTP_201_CREATED)


class LoginView(_PublicAuthView):
    throttle_classes = [AuthRateThrottle, LoginAccountThrottle]
    throttle_scope = "auth"

    @extend_schema(
        tags=AUTH_TAG,
        summary="Sign in",
        request=LoginSerializer,
        responses={200: OpenApiResponse(_user_envelope, description="Signed in; auth cookies set"), 401: None},
    )
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = authenticate(
            request, email=serializer.validated_data["email"].lower(), password=serializer.validated_data["password"]
        )
        if user is None:
            raise AuthenticationFailed("Invalid email or password.", code="invalid_credentials")
        update_last_login(None, user)
        return self.signed_in_response(user)


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
