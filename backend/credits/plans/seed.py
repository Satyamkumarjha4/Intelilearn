"""The plans of the spec (§5.1, plan D1) as data, and how they get into the table. Migration `0007_plan_seed` seeds
them once (at the original prices; `0009_raise_plan_prices` moved the rows to the current ones);
`PlanSeed` is the same list for the code that needs it again (the test fixtures: a test that flushes the database
takes the
migration's rows with it). Only plans with no row at all are added: an edited or switched-off plan is left alone."""

from ..models import Plan


class PlanSeed:
    PLANS = [
        # key, name, credits, period_days, price_paise, max_quantity, sort
        # Prices as raised on 2026-11-15 (migration 0009): ₹2 a credit, ₹147 a week, ₹597 and ₹837 for 28 days.
        ("one_time", "One-time credits", 0, 365, 200, 1, 1),
        ("weekly_pro", "Weekly Pro", 100, 7, 14700, 12, 2),
        ("monthly_pro", "Monthly Pro", 500, 28, 59700, 1, 3),
        ("pro_plus", "Pro Plus", 750, 28, 83700, 1, 4),
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
