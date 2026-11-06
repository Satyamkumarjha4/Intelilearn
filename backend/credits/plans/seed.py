"""The plans of the spec (§5.1, plan D1) as data, and how they get into the table. Migration `0007_plan_seed` seeds
them once;
`PlanSeed` is the same list for the code that needs it again (the test fixtures: a test that flushes the database
takes the
migration's rows with it). Only plans with no row at all are added: an edited or switched-off plan is left alone."""

from ..models import Plan


class PlanSeed:
    PLANS = [
        # key, name, credits, period_days, price_paise, max_quantity, sort
        ("one_time", "One-time credits", 0, 365, 100, 1, 1),
        ("weekly_pro", "Weekly Pro", 100, 7, 4900, 12, 2),
        ("monthly_pro", "Monthly Pro", 500, 28, 19900, 1, 3),
        ("pro_plus", "Pro Plus", 750, 28, 27900, 1, 4),
    ]

    def apply(self) -> int:
        known = set(Plan.objects.values_list("key", flat=True))
        missing = [row for row in self.PLANS if row[0] not in known]
        Plan.objects.bulk_create(
            [
                Plan(key=k, name=n, credits=c, period_days=d, price_paise=p, max_quantity=m, sort=s, active=True)
                for k, n, c, d, p, m, s in missing
            ]
        )
        return len(missing)
