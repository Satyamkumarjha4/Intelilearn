from django.db import migrations
from django.db.models import F


def copy_cost(apps, schema_editor):
    """Every recorded cost is in US dollars already: the new column starts as a copy of the old one."""
    apps.get_model("llm_registry", "ModelCall").objects.filter(cost__isnull=False).update(cost_usd=F("cost"))


class Migration(migrations.Migration):
    dependencies = [("llm_registry", "0007_model_prices_and_strategy_fields")]

    operations = [migrations.RunPython(copy_cost, migrations.RunPython.noop)]
