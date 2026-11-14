"""Shapes of the console's sign-in screens: a learner's verification panel, the people waiting for a code, the
abuse board and the sign-up challenge's switch. Services return plain dicts; these say what each looks like (and
so what Swagger shows). Nothing here is ever a code, a hash or a secret."""

from rest_framework import serializers

SOURCES = ["code", "google", "microsoft", "staff", "operator", "legacy", ""]
CODE_STATES = ["live", "used", "cancelled", "dead", "expired"]


class VerificationLearnerSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField(allow_blank=True)
    email = serializers.EmailField()


class VerificationStateSerializer(serializers.Serializer):
    verified = serializers.BooleanField()
    verified_at = serializers.DateTimeField(allow_null=True)
    source = serializers.ChoiceField(
        choices=SOURCES, allow_blank=True, help_text="Who proved or vouched for the email."
    )
    legacy = serializers.BooleanField(help_text="Existed before verification; never proved.")
    closed = serializers.BooleanField()
    erased = serializers.BooleanField()
    can_resend = serializers.BooleanField(help_text="An open, unverified account: a new code can be sent.")
    can_mark_verified = serializers.BooleanField()
    can_unlock = serializers.BooleanField()


class VerificationIdentitySerializer(serializers.Serializer):
    provider = serializers.CharField()
    linked_at = serializers.DateTimeField()
    last_sign_in_at = serializers.DateTimeField(allow_null=True)
    hosted_domain = serializers.CharField(allow_blank=True)


class VerificationCodeRowSerializer(serializers.Serializer):
    purpose = serializers.CharField()
    created_at = serializers.DateTimeField()
    expires_at = serializers.DateTimeField()
    tries = serializers.IntegerField()
    max_tries = serializers.IntegerField()
    state = serializers.ChoiceField(choices=CODE_STATES, help_text="Never the code itself.")


class VerificationMailRowSerializer(serializers.Serializer):
    kind = serializers.CharField()
    status = serializers.CharField()
    error = serializers.CharField(allow_blank=True, help_text="A short reason; never a code or a body.")
    created_at = serializers.DateTimeField()
    sent_at = serializers.DateTimeField(allow_null=True)


class VerificationLockSerializer(serializers.Serializer):
    locked_until = serializers.DateTimeField()
    strikes = serializers.IntegerField()


class VerificationSignupRecordSerializer(serializers.Serializer):
    ip = serializers.CharField(allow_null=True)
    email_domain = serializers.CharField()
    method = serializers.CharField()
    created_at = serializers.DateTimeField()


class VerificationPanelSerializer(serializers.Serializer):
    learner = VerificationLearnerSerializer()
    state = VerificationStateSerializer()
    sign_in_methods = serializers.ListField(
        child=serializers.CharField(), help_text="`password` and each linked provider."
    )
    identities = VerificationIdentitySerializer(many=True)
    codes = VerificationCodeRowSerializer(many=True, help_text="The last five, newest first.")
    mail = VerificationMailRowSerializer(many=True, help_text="The last five emails sent to the address.")
    lock = VerificationLockSerializer(allow_null=True)
    signup_record = VerificationSignupRecordSerializer(allow_null=True, help_text="Kept 30 days.")


class ReasonInputSerializer(serializers.Serializer):
    reason = serializers.CharField(
        trim_whitespace=True,
        allow_blank=True,
        required=False,
        help_text="Required, at least 10 characters. Kept in the change log.",
    )


class PendingSignupRowSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    email = serializers.EmailField()
    name = serializers.CharField()
    created_at = serializers.DateTimeField()
    expires_at = serializers.DateTimeField()
    code_tries = serializers.IntegerField(
        allow_null=True, help_text="Tries used on the live code; null when it has none."
    )
    code_max_tries = serializers.IntegerField(allow_null=True)
    code_expires_at = serializers.DateTimeField(allow_null=True)
    locked_until = serializers.DateTimeField(
        allow_null=True, help_text="Null, or a time already past, when not locked."
    )


class PendingSignupPageSerializer(serializers.Serializer):
    next = serializers.CharField(allow_null=True)
    previous = serializers.CharField(allow_null=True)
    results = PendingSignupRowSerializer(many=True)


class SignupActionSerializer(serializers.Serializer):
    sent = serializers.BooleanField(required=False)
    unlocked = serializers.BooleanField(required=False)
    note = serializers.CharField()


class SignupApprovedSerializer(serializers.Serializer):
    learner_id = serializers.UUIDField()
    signs_in_with = serializers.ChoiceField(choices=["google_or_reset"])
    note = serializers.CharField(help_text="Tells staff to confirm the person out of band first.")


class AbuseDaySerializer(serializers.Serializer):
    day = serializers.DateField()
    accounts_made = serializers.IntegerField()
    codes_sent = serializers.IntegerField()
    failed_checks = serializers.IntegerField()
    disposable_refused = serializers.IntegerField()
    captcha_failed = serializers.IntegerField()


class AbuseTopSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="A client address or an email domain; never an email.")
    count = serializers.IntegerField()


class ChallengeStateSerializer(serializers.Serializer):
    captcha_enabled = serializers.BooleanField()
    configured = serializers.BooleanField(help_text="Both Turnstile keys are in the environment.")
    missing = serializers.ListField(child=serializers.CharField(), help_text="Names of settings that are not set.")
    provider = serializers.CharField(allow_blank=True)


class AbuseReportSerializer(serializers.Serializer):
    days = AbuseDaySerializer(many=True, help_text="The last 14 UTC days, oldest first, today last.")
    top_addresses = AbuseTopSerializer(many=True, help_text="The last 24 hours.")
    top_domains = AbuseTopSerializer(many=True, help_text="The last 24 hours.")
    locked_emails = serializers.IntegerField()
    waiting_signups = serializers.IntegerField()
    challenge = ChallengeStateSerializer()


class AuthSettingsInputSerializer(serializers.Serializer):
    captcha_enabled = serializers.BooleanField()
