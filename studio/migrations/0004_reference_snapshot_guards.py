import importlib
from django.db import migrations

def rebuild(apps,schema_editor):
    guards=importlib.import_module('studio.migrations.0002_history_and_tenant_guards')
    guards.uninstall(apps,schema_editor)
    guards.install(apps,schema_editor)
    table='studio_resolvedreference'
    with schema_editor.connection.cursor() as cursor:
        if schema_editor.connection.vendor=='sqlite':
            for op in ('UPDATE','DELETE'):
                cursor.execute(f"CREATE TRIGGER {table}_immutable_{op.lower()} BEFORE {op} ON {table} BEGIN SELECT RAISE(ABORT, 'Reference snapshots are immutable'); END")
        elif schema_editor.connection.vendor=='postgresql':
            cursor.execute(f"CREATE FUNCTION {table}_immutable_guard() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'Reference snapshots are immutable'; END; $$ LANGUAGE plpgsql")
            cursor.execute(f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION {table}_immutable_guard()")

class Migration(migrations.Migration):
    dependencies=[('studio','0003_resolvedreference')]
    operations=[migrations.RunPython(rebuild,migrations.RunPython.noop)]
