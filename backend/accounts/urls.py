from django.urls import path

from . import views

urlpatterns = [
    path("auth/csrf", views.CsrfView.as_view(), name="auth-csrf"),
    path("auth/register", views.RegisterView.as_view(), name="auth-register"),
    path("auth/verify", views.VerifyView.as_view(), name="auth-verify"),
    path("auth/verify/resend", views.VerifyResendView.as_view(), name="auth-verify-resend"),
    path("auth/password/forgot", views.ForgotPasswordView.as_view(), name="auth-password-forgot"),
    path("auth/password/reset", views.ResetPasswordView.as_view(), name="auth-password-reset"),
    path("auth/login", views.LoginView.as_view(), name="auth-login"),
    path("auth/refresh", views.RefreshView.as_view(), name="auth-refresh"),
    path("auth/logout", views.LogoutView.as_view(), name="auth-logout"),
    path("auth/me", views.MeView.as_view(), name="auth-me"),
    path("dev/outbox", views.DevOutboxView.as_view(), name="dev-outbox"),
    path("profile", views.ProfileView.as_view(), name="profile"),
    path("profile/options", views.ProfileOptionsView.as_view(), name="profile-options"),
]
