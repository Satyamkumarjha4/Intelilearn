from django.db import migrations

#: ids the providers have stopped serving or rerouted (docs/to_be_developed/model-strategy.md, decision 9)
RETIRED = ["gemini-3.5-flash", "gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro", "llama-3.3-70b-versatile"]


def retire(apps, schema_editor):
    """Take the retired models out of every chain that has another layer and delete them. A model that is a node's
    only layer is kept, switched off and marked deprecated, so the node's missing model stays visible."""
    LLMModel = apps.get_model("llm_registry", "LLMModel")
    Binding = apps.get_model("llm_registry", "NodeModelBinding")
    for model in LLMModel.objects.filter(name__in=RETIRED):
        others = Binding.objects.exclude(model=model)
        only_layer = [b for b in Binding.objects.filter(model=model) if not others.filter(node=b.node).exists()]
        if only_layer:
            Binding.objects.filter(model=model).exclude(pk__in=[b.pk for b in only_layer]).delete()
            model.is_enabled, model.status = False, "deprecated"
            model.save(update_fields=["is_enabled", "status"])
        else:
            Binding.objects.filter(model=model).delete()
            model.delete()


class Migration(migrations.Migration):
    dependencies = [("llm_registry", "0008_copy_cost_to_cost_usd")]

    operations = [migrations.RunPython(retire, migrations.RunPython.noop)]
