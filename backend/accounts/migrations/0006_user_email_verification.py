"""Phase 11.0: whether and how an account's email was proved, and the canonical email that makes one inbox one account.

Every account that exists now is marked verified with the source `legacy` (it keeps what it has; `legacy` is never counted
as proved by the owner), except an erased one. `email_canonical` is filled for every row; where two existing accounts
collapse to the same canonical address the earlier one (by `date_joined`, then id) keeps it and the later one gets a marked
address that cannot collide (`dup:<id>:<address>`), which the console lists. Undoing drops the columns and keeps the users.
"""

from django.db import migrations, models

from accounts.emailrules.canonical import EmailCanonicalizer, MalformedEmail


def fill(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    seen: set[str] = set()
    for user in User.objects.order_by("date_joined", "pk").iterator():
        try:
            canonical = EmailCanonicalizer.of(user.email)
        except MalformedEmail:
            canonical = user.email.strip().lower()
        if canonical in seen:
            canonical = f"dup:{user.pk}:{user.email.strip().lower()}"
        seen.add(canonical)
        fields = {"email_canonical": canonical}
        if user.deleted_at is None:
            fields.update(email_verified_at=user.date_joined, email_verification_source="legacy")
        User.objects.filter(pk=user.pk).update(**fields)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0005_user_deleted_at")]

    operations = [
        migrations.AddField("user", "email_verified_at", models.DateTimeField(blank=True, null=True)),
        migrations.AddField(
            "user", "email_verification_source", models.CharField(blank=True, default="", max_length=12)
        ),
        migrations.AddField("user", "email_canonical", models.CharField(editable=False, max_length=320, null=True)),
        migrations.RunPython(fill, migrations.RunPython.noop),
        migrations.AlterField(
            "user", "email_canonical", models.CharField(editable=False, max_length=320, unique=True)
        ),
    ]
