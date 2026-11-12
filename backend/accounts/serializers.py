from django.contrib.auth.hashers import make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .emailrules.policy import EmailPolicy, EmailRefused
from .models import Profile, User
from .timezones import ProfileTimezone, TimeZoneNames
from .verification.signup import SignupRequest

CONSENT_MESSAGE = "Please confirm to continue."


class UserSerializer(serializers.ModelSerializer):
    profile_complete = serializers.BooleanField(source="profile.is_complete", read_only=True)

    class Meta:
        model = User
        fields = ["id", "email", "name", "profile_complete", "is_staff"]
        read_only_fields = fields


class RegisterSerializer(serializers.Serializer):
    policy = EmailPolicy()  # which addresses may sign up (not a field)

    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False, style={"input_type": "password"})
    name = serializers.CharField(max_length=150)
    accept_terms = serializers.BooleanField(
        write_only=True,
        error_messages={"required": CONSENT_MESSAGE, "null": CONSENT_MESSAGE, "invalid": CONSENT_MESSAGE},
        help_text="Must be true: 18 or older, or a parent or guardian agreed to the Terms and Privacy Policy.",
    )
    timezone = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        max_length=TimeZoneNames.MAX_LENGTH,
        help_text=(
            "The browser's IANA time zone (for example `Asia/Kolkata`), which sets the learner's day. Optional: blank "
            "or unknown name is ignored (never an error), and the zone stays unset until the learner chooses one."
        ),
    )

    def validate_accept_terms(self, value):
        if value is not True:
            raise serializers.ValidationError(CONSENT_MESSAGE)
        return value

    def validate_email(self, value):
        """The address as typed (the domain lowercased, as every mail system does), checked against the sign-up
        policy. Whether an account has it is not asked here: nothing in the answer may tell."""
        email = User.objects.normalize_email(value.strip())
        try:
            self.policy.check(email)
        except EmailRefused as refused:
            raise serializers.ValidationError(refused.message) from refused
        return email

    def validate(self, attrs):
        # Validators such as "too similar to the email" need the would-be user.
        try:
            validate_password(attrs["password"], user=User(email=attrs["email"], name=attrs["name"]))
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": list(exc.messages)}) from exc
        return attrs

    def signup_request(self) -> SignupRequest:
        """What `SignupVerification.start` needs. The password is **always** hashed, whether or not the address has an
        account, so the request takes the same time either way (no enumeration by timing)."""
        data = self.validated_data
        return SignupRequest(
            email=data["email"],
            name=data["name"],
            password_hash=make_password(data["password"]),
            timezone=data.get("timezone", "") if TimeZoneNames.is_valid(data.get("timezone", "")) else "",
            terms_version=User.TERMS_VERSION,
            terms_accepted_at=timezone.now(),
        )


class VerifySerializer(serializers.Serializer):
    """The code check. Anything that does not parse is answered like a wrong code (in the view), never with field
    errors."""

    PURPOSES = ("signup", "login")
    email = serializers.EmailField()
    code = serializers.CharField(max_length=32, trim_whitespace=True)
    purpose = serializers.ChoiceField(choices=PURPOSES)


class ForgotSerializer(serializers.Serializer):
    email = serializers.EmailField()


class ResetSerializer(serializers.Serializer):
    """The new password. `email` and `code` that do not parse are answered like a wrong code (in the view); the password
    is judged against the typed address only, so the answer is the same whether or not an account has it."""

    email = serializers.EmailField()
    code = serializers.CharField(max_length=32, trim_whitespace=True)
    new_password = serializers.CharField(write_only=True, trim_whitespace=False, style={"input_type": "password"})


class FinishSerializer(serializers.Serializer):
    """The last step of signing in with a provider. `OAuthSignIn.finish` checks the form and owns the rules (the
    terms, a name); this describes the request for the API schema."""

    name = serializers.CharField(max_length=150)
    accept_terms = serializers.BooleanField(
        help_text="Must be true: the same confirmation as when creating an account."
    )
    timezone = serializers.CharField(required=False, allow_blank=True, max_length=TimeZoneNames.MAX_LENGTH)


class ResendSerializer(serializers.Serializer):
    email = serializers.EmailField()
    purpose = serializers.ChoiceField(choices=VerifySerializer.PURPOSES)


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False, style={"input_type": "password"})


class ProfileSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source="user.name", max_length=150, required=False)
    email = serializers.EmailField(source="user.email", read_only=True)
    profile_complete = serializers.BooleanField(source="is_complete", read_only=True)
    timezone = serializers.CharField(
        required=False,
        max_length=TimeZoneNames.MAX_LENGTH,
        help_text=(
            "The learner's IANA time zone, which sets their day (daily credit, streak). Blank until set. Changing it "
            "once it is set is allowed once every 30 days: `409 timezone_locked` otherwise."
        ),
    )
    effective_timezone = serializers.CharField(
        read_only=True, help_text="The zone in force: `timezone`, or Asia/Kolkata."
    )
    timezone_locked_until = serializers.SerializerMethodField(
        help_text="When the zone can next be changed, or null when it can be changed now."
    )

    class Meta:
        model = Profile
        fields = [
            "name",
            "email",
            "education_level",
            "grade_or_year",
            "field_of_study",
            "preferred_language",
            "learning_preference",
            "goal",
            "notes",
            "timezone",
            "effective_timezone",
            "timezone_locked_until",
            "profile_complete",
            "updated_at",
        ]
        read_only_fields = ["updated_at"]
        # Onboarding must fill these in; a PATCH can still change other fields on their own.
        extra_kwargs = {
            field: {
                "required": True,
                "allow_blank": False,
                # An empty select arrives as "" and would otherwise read '"" is not a valid choice.'
                "error_messages": {"invalid_choice": "Please choose one of the options."},
            }
            for field in Profile.REQUIRED_FOR_ONBOARDING
        }

    def validate_timezone(self, value):
        if not TimeZoneNames.is_valid(value):
            raise serializers.ValidationError("Choose a time zone from the list, such as Asia/Kolkata.")
        return value

    @extend_schema_field(serializers.DateTimeField(allow_null=True))
    def get_timezone_locked_until(self, profile):
        until = ProfileTimezone().locked_until(profile)
        return serializers.DateTimeField().to_representation(until) if until else None

    def update(self, instance, validated_data):
        # First, so a refused change leaves everything else in the same request unsaved.
        if "timezone" in validated_data:
            ProfileTimezone().apply(instance, validated_data.pop("timezone"))
        user_data = validated_data.pop("user", {})
        if "name" in user_data:
            instance.user.name = user_data["name"]
            instance.user.save(update_fields=["name"])
        return super().update(instance, validated_data)


class ChoiceSerializer(serializers.Serializer):
    value = serializers.CharField()
    label = serializers.CharField()


class ProfileOptionsSerializer(serializers.Serializer):
    """The shape of `GET /api/profile/options` (documentation only: the view builds the payload itself)."""

    education_level = ChoiceSerializer(many=True)
    learning_preference = ChoiceSerializer(many=True)
    goal = ChoiceSerializer(many=True)
    preferred_language = ChoiceSerializer(many=True)
