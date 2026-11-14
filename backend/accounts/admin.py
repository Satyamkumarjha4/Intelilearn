from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import AuthEvent, AuthSettings, Profile, SignupRecord, User


class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False
    readonly_fields = ["updated_at"]


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    inlines = [ProfileInline]
    ordering = ["email"]
    list_display = ["email", "name", "is_staff", "is_active", "date_joined", "last_login"]
    list_filter = ["is_staff", "is_superuser", "is_active"]
    search_fields = ["email", "name"]
    readonly_fields = [
        "email",
        "email_verified_at",
        "email_verification_source",
        "email_canonical",
        "date_joined",
        "last_login",
        "terms_accepted_at",
        "terms_version",
    ]
    fieldsets = [
        (None, {"fields": ["email", "password"]}),
        ("Email proof", {"fields": ["email_verified_at", "email_verification_source", "email_canonical"]}),
        ("Personal info", {"fields": ["name"]}),
        ("Permissions", {"fields": ["is_active", "is_staff", "is_superuser", "groups", "user_permissions"]}),
        ("Dates", {"fields": ["last_login", "date_joined"]}),
        ("Consent", {"fields": ["terms_accepted_at", "terms_version"]}),
    ]

    def get_readonly_fields(self, request, obj=None):
        """Nothing changes an account's email (the signup credits and the one-inbox rule hang on it): it is typed
        when an
        account is added and is read-only after."""
        fields = super().get_readonly_fields(request, obj)
        return fields if obj is not None else [f for f in fields if f != "email"]

    add_fieldsets = [
        (None, {"classes": ["wide"], "fields": ["email", "name", "password1", "password2"]}),
    ]


class ReadOnlyAdmin(admin.ModelAdmin):
    """For tables the app writes and a person only reads: the records behind the abuse board. Nothing can be added,
    changed or deleted here, so an entry cannot be forged or removed to hide what happened (a switch that staff may
    change is changed in the console, where it is audited)."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SignupRecord)
class SignupRecordAdmin(ReadOnlyAdmin):
    list_display = ["created_at", "method", "email_domain", "ip", "user"]
    list_filter = ["method"]
    search_fields = ["email_domain", "ip"]
    date_hierarchy = "created_at"


@admin.register(AuthEvent)
class AuthEventAdmin(ReadOnlyAdmin):
    list_display = ["created_at", "kind", "email_domain", "ip"]
    list_filter = ["kind"]
    search_fields = ["email_domain", "ip"]
    date_hierarchy = "created_at"


@admin.register(AuthSettings)
class AuthSettingsAdmin(ReadOnlyAdmin):
    list_display = ["__str__", "captcha_enabled", "updated_at"]
