"""Seeds the price table with the plan's prices (docs/archive/credits-implementation-plan.md §5.4, as corrected by
changelog P2: study sheets are priced by the number of sheets, whatever the score).

The list is written out here, not imported, so this migration means the same thing whatever the code later says. It adds a
price only where the key has no row at all, so it never overwrites one an administrator already set; undoing it removes only
the rows it could have added.
"""

from datetime import UTC, datetime

from django.db import migrations

PRICES = [
    ("lesson.check", 3, "Quick check"),
    ("lesson.check_recommended", 2, "Quick check (recommended lesson)"),
    ("lesson.full", 10, "Your lesson"),
    ("lesson.full_recommended", 9, "Your lesson (recommended)"),
    ("lesson.full_from_quiz", 9, "Lesson from your quiz result"),
    ("lesson.rest", 7, "Your lesson, after the Quick check"),
    ("sheets.after_check", 2, "Both study sheets, after the Quick check"),
    ("sheets.after_check_single", 0, "One study sheet, after the Quick check"),
    ("sheet.each", 2, "Study sheet"),
    ("sheet.grounded_extra", 1, "Built from your lesson's pages"),
    ("followup.foundation", 5, "Foundation lesson"),
    ("followup.advanced", 7, "Advanced lesson"),
    ("test.retake", 2, "Take the test again with new questions"),
    ("quiz.tier_5", 1, "Quick quiz, 5 questions"),
    ("quiz.tier_10", 2, "Quick quiz, 10 or 15 questions"),
    ("quiz.tier_20", 3, "Quick quiz, 20 to 30 questions"),
    ("quiz.extra", 1, "Quiz from your lessons, or with a warm-up"),
    ("streak.repair", 1, "Repair a missed day"),
]


def seed(apps, schema_editor):
    ActionPrice = apps.get_model("credits", "ActionPrice")
    known = set(ActionPrice.objects.values_list("key", flat=True))
    now = datetime.now(UTC)
    ActionPrice.objects.bulk_create(
        [
            ActionPrice(key=key, credits=credits, label=label, active=True, updated_at=now)
            for key, credits, label in PRICES
            if key not in known
        ]
    )


def unseed(apps, schema_editor):
    apps.get_model("credits", "ActionPrice").objects.filter(key__in=[key for key, _, _ in PRICES]).delete()


class Migration(migrations.Migration):
    dependencies = [("credits", "0003_action_price")]

    operations = [migrations.RunPython(seed, unseed)]
