from django.db import migrations, models
from django.db.models.functions import Length

LANGUAGES = {"en", "hi", "es", "fr", "de"}
NOTES_MAX_LENGTH = 2000


def make_rows_fit(apps, schema_editor):
    """The constraints below only hold if the stored rows obey them: an unknown language becomes English and a long note
    is cut to the limit."""
    Profile = apps.get_model("accounts", "Profile")
    profiles = Profile.objects.using(schema_editor.connection.alias)
    profiles.exclude(preferred_language__in=LANGUAGES).update(preferred_language="en")
    too_long = profiles.annotate(size=Length("notes")).filter(size__gt=NOTES_MAX_LENGTH).only("pk", "notes")
    for profile in too_long:
        profile.notes = profile.notes[:NOTES_MAX_LENGTH]
        profile.save(update_fields=["notes"])


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(make_rows_fit, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="profile",
            name="preferred_language",
            field=models.CharField(
                choices=[("en", "English"), ("hi", "Hindi"), ("es", "Spanish"), ("fr", "French"), ("de", "German")],
                default="en",
                max_length=10,
            ),
        ),
        migrations.AlterField(
            model_name="profile",
            name="notes",
            field=models.TextField(blank=True, max_length=2000),
        ),
    ]
