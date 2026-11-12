"""Phase 11.0: the console's sign-in switches (`AuthSettings`) and the mail log (`OutboundMail`)."""

import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0006_user_email_verification")]

    operations = [
        migrations.CreateModel(
            name="AuthSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "captcha_enabled",
                    models.BooleanField(
                        default=False,
                        help_text="Ask a visitor to pass a challenge when signing up and asking for a code (phase 11.4).",
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"verbose_name_plural": "auth settings"},
        ),
        migrations.CreateModel(
            name="OutboundMail",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(max_length=30)),
                ("to_email", models.EmailField(max_length=254)),
                ("subject", models.CharField(blank=True, max_length=200)),
                ("backend", models.CharField(max_length=20)),
                (
                    "status",
                    models.CharField(
                        choices=[("queued", "Queued"), ("sent", "Sent"), ("failed", "Failed")],
                        default="queued",
                        max_length=10,
                    ),
                ),
                ("attempts", models.PositiveSmallIntegerField(default=0)),
                ("provider_message_id", models.CharField(blank=True, max_length=200)),
                ("error", models.CharField(blank=True, help_text="A short reason, never a code or a body.", max_length=255)),
                ("body_text", models.TextField(blank=True, help_text="Kept by the throwaway-stack outbox backend only.")),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "indexes": [
                    models.Index(fields=["to_email", "-created_at"], name="accounts_ou_to_emai_a59e07_idx"),
                    models.Index(fields=["created_at"], name="accounts_ou_created_13a167_idx"),
                ]
            },
        ),
    ]
