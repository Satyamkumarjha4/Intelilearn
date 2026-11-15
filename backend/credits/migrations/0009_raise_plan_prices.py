"""The approved price change of 2026-11-15: one-time credits cost twice what they did and the subscription plans three
times. What a plan gives (credits, days) and what an action costs in credits do not change.

    One-time credits  100 -> 200 paise a credit (so the smallest purchase, 10 credits, is 2,000 paise)
    Weekly Pro        4,900 -> 14,700 paise a week
    Monthly Pro       19,900 -> 59,700 paise
    Pro Plus          27,900 -> 83,700 paise

It goes from the prices migration 0007 seeded straight to the final ones. Only the `Plan` rows change. A purchase keeps
the amount it was paid, a period and a bucket keep the credits they were given. A plan whose price is not the original
(an admin edited it in the console) is left alone, and undoing the migration likewise only touches a plan still at the
final price; so neither direction overwrites a hand-made figure. The figures are written out here, not imported, so this
migration means the same whatever the code later says.
"""

from django.db import migrations

CHANGES = [
    # key, original price_paise (what 0007 seeded), final price_paise
    ("one_time", 100, 200),
    ("weekly_pro", 4900, 14700),
    ("monthly_pro", 19900, 59700),
    ("pro_plus", 27900, 83700),
]


def raise_prices(apps, schema_editor):
    Plan = apps.get_model("credits", "Plan")
    for key, old, new in CHANGES:
        Plan.objects.filter(key=key, price_paise=old).update(price_paise=new)


def lower_prices(apps, schema_editor):
    Plan = apps.get_model("credits", "Plan")
    for key, old, new in CHANGES:
        Plan.objects.filter(key=key, price_paise=new).update(price_paise=old)


class Migration(migrations.Migration):
    dependencies = [("credits", "0008_retire_paise_per_credit")]

    operations = [migrations.RunPython(raise_prices, lower_prices)]
