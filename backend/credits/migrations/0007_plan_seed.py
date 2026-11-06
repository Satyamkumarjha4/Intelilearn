"""Seeds the plans of the spec (§5.1, plan D1): one-time credits at 100 paise a credit; Weekly Pro 100 credits for 7 days at
4,900 paise (up to 12 weeks at once); Monthly Pro 500 credits for 28 days at 19,900 paise; Pro Plus 750 credits for 28 days at
27,900 paise.

The list is written out here, not imported, so this migration means the same thing whatever the code later says. A plan is added
only where its key has no row at all, so an edited or switched-off plan is never overwritten; undoing it removes only these keys.
"""

from django.db import migrations

PLANS = [
    # key, name, credits, period_days, price_paise, max_quantity, sort
    ("one_time", "One-time credits", 0, 365, 100, 1, 1),
    ("weekly_pro", "Weekly Pro", 100, 7, 4900, 12, 2),
    ("monthly_pro", "Monthly Pro", 500, 28, 19900, 1, 3),
    ("pro_plus", "Pro Plus", 750, 28, 27900, 1, 4),
]


def seed(apps, schema_editor):
    Plan = apps.get_model("credits", "Plan")
    known = set(Plan.objects.values_list("key", flat=True))
    Plan.objects.bulk_create(
        [
            Plan(key=k, name=n, credits=c, period_days=d, price_paise=p, max_quantity=m, sort=s, active=True)
            for k, n, c, d, p, m, s in PLANS
            if k not in known
        ]
    )


def unseed(apps, schema_editor):
    apps.get_model("credits", "Plan").objects.filter(key__in=[row[0] for row in PLANS]).delete()


class Migration(migrations.Migration):
    dependencies = [("credits", "0006_plans")]

    operations = [migrations.RunPython(seed, unseed)]
