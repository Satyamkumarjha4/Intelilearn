"""The contract step (plan §7.7, step 5): the lesson's test column and the retired test-size settings go.

`Lesson.final_test` is replaced by the first set on the record of questions (0019). `final_test_min` and
`final_test_max` have been read by nothing since the test became a fixed ten questions (phase 9.2). Reversible: the
columns come back empty or at their old defaults, and going back through 0019 refills `final_test`.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("lessons", "0019_first_set_backfill")]
    operations = [
        migrations.RemoveField(model_name="lesson", name="final_test"),
        migrations.RemoveField(model_name="flowsettings", name="final_test_min"),
        migrations.RemoveField(model_name="flowsettings", name="final_test_max"),
    ]
