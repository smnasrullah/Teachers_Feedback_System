"""Database-level append-only guard for the audit log (PostgreSQL only).

Revokes UPDATE/DELETE from the application role and PUBLIC, and adds a trigger that
rejects UPDATE/DELETE even for roles that bypass privileges (owner re-grant, superuser).
TRUNCATE stays allowed: test-database flushes use it, and an emptied log is evident.
SQLite (local quick runs) relies on the model/queryset guards.
"""

from django.db import migrations

TABLE = "auditlog_auditevent"

FORWARD = [
    """
    CREATE OR REPLACE FUNCTION auditlog_block_mutation() RETURNS trigger AS $$
    BEGIN
        RAISE EXCEPTION 'audit log is append-only' USING ERRCODE = 'insufficient_privilege';
    END;
    $$ LANGUAGE plpgsql
    """,
    f"""
    CREATE TRIGGER auditlog_auditevent_append_only
    BEFORE UPDATE OR DELETE ON {TABLE}
    FOR EACH ROW EXECUTE FUNCTION auditlog_block_mutation()
    """,
    f"REVOKE UPDATE, DELETE ON {TABLE} FROM PUBLIC",
    f"REVOKE UPDATE, DELETE ON {TABLE} FROM CURRENT_USER",
]

BACKWARD = [
    f"GRANT UPDATE, DELETE ON {TABLE} TO CURRENT_USER",
    f"DROP TRIGGER IF EXISTS auditlog_auditevent_append_only ON {TABLE}",
    "DROP FUNCTION IF EXISTS auditlog_block_mutation()",
]


def _run(statements):
    def apply(apps, schema_editor):
        if schema_editor.connection.vendor == "postgresql":
            for statement in statements:
                schema_editor.execute(statement)

    return apply


class Migration(migrations.Migration):
    dependencies = [("auditlog", "0001_initial")]

    operations = [migrations.RunPython(_run(FORWARD), _run(BACKWARD))]
