"""The approved price change of 2026-11-15: every plan costs twice what it did. What a plan gives (credits, days) and what
an action costs in credits do not change.

    One-time credits  100 -> 200 paise a credit (so the smallest purchase, 10 credits, is 2,000 paise)
    Weekly Pro        4,900 -> 9,800 paise a week
    Monthly Pro       19,900 -> 39,800 paise
    Pro Plus          27,900 -> 55,800 paise

Only the `Plan` rows change. A purchase keeps the amount it was paid, a period and a bucket keep the credits they were
given. A plan whose price is not the old one (an admin edited it in the console) is left alone, and undoing the migration
likewise only touches a plan still at the new price; so neither direction overwrites a hand-made figure. The figures are
written out here, not imported, so this migration means the same whatever the code later says.
"""

from django.db import migrations

CHANGES = [
    # key, old price_paise, new price_paise
    ("one_time", 100, 200),
    ("weekly_pro", 4900, 9800),
    ("monthly_pro", 19900, 39800),
    ("pro_plus", 27900, 55800),
]


def double(apps, schema_editor):
    Plan = apps.get_model("credits", "Plan")
    for key, old, new in CHANGES:
        Plan.objects.filter(key=key, price_paise=old).update(price_paise=new)


def halve(apps, schema_editor):
    Plan = apps.get_model("credits", "Plan")
    for key, old, new in CHANGES:
        Plan.objects.filter(key=key, price_paise=new).update(price_paise=old)


class Migration(migrations.Migration):
    dependencies = [("credits", "0008_retire_paise_per_credit")]

    operations = [migrations.RunPython(double, halve)]
