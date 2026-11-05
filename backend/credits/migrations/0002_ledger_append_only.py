"""The ledger is append-only in the database too (credits plan T5): a trigger refuses any UPDATE or DELETE of a
`CreditTransaction` row, whoever sends it (the model guard, a shell, the admin, a dashboard). It is a migration so the
rule is versioned with the table. TRUNCATE is not refused: the test suite flushes tables with it, and it needs a
privilege the app's role does not need."""

from django.db import migrations

CREATE = """
CREATE FUNCTION credits_transaction_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'credits_credittransaction is append-only: % is not allowed', TG_OP
        USING ERRCODE = 'integrity_constraint_violation';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER credits_transaction_append_only
    BEFORE UPDATE OR DELETE ON credits_credittransaction
    FOR EACH ROW EXECUTE FUNCTION credits_transaction_append_only();
"""

DROP = """
DROP TRIGGER credits_transaction_append_only ON credits_credittransaction;
DROP FUNCTION credits_transaction_append_only();
"""


class Migration(migrations.Migration):
    dependencies = [("credits", "0001_ledger")]

    operations = [migrations.RunSQL(CREATE, reverse_sql=DROP)]
