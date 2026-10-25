from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from rest_framework import serializers

from .models import Profile, User

CONSENT_MESSAGE = "Please confirm to continue."


class UserSerializer(serializers.ModelSerializer):
    profile_complete = serializers.BooleanField(source="profile.is_complete", read_only=True)

    class Meta:
        model = User
        fields = ["id", "email", "name", "profile_complete", "is_staff"]
        read_only_fields = fields


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False, style={"input_type": "password"})
    name = serializers.CharField(max_length=150)
    accept_terms = serializers.BooleanField(
        write_only=True,
        error_messages={"required": CONSENT_MESSAGE, "null": CONSENT_MESSAGE, "invalid": CONSENT_MESSAGE},
        help_text="Must be true: 18 or older, or a parent or guardian agreed to the Terms and Privacy Policy.",
    )

    def validate_accept_terms(self, value):
        if value is not True:
            raise serializers.ValidationError(CONSENT_MESSAGE)
        return value

    def validate_email(self, value):
        email = value.strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return email

    def validate(self, attrs):
        # Validators such as "too similar to the email" need the would-be user.
        try:
            validate_password(attrs["password"], user=User(email=attrs["email"], name=attrs["name"]))
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": list(exc.messages)}) from exc
        return attrs

    def create(self, validated_data):
        validated_data.pop("accept_terms")  # only a yes gets this far; what is kept is when and to which version
        return User.objects.create_user(
            **validated_data, terms_accepted_at=timezone.now(), terms_version=User.TERMS_VERSION
        )


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False, style={"input_type": "password"})


class ProfileSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source="user.name", max_length=150, required=False)
    email = serializers.EmailField(source="user.email", read_only=True)
    profile_complete = serializers.BooleanField(source="is_complete", read_only=True)

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

    def update(self, instance, validated_data):
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
