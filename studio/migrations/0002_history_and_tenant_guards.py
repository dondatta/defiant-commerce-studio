from django.db import migrations

IMMUTABLE=('generation','generationresult','generationreference','reviewdecision','auditevent')

def install(apps,schema_editor):
    vendor=schema_editor.connection.vendor
    if vendor not in ('sqlite','postgresql'): return
    models=list(apps.get_app_config('studio').get_models())
    with schema_editor.connection.cursor() as cursor:
        for model in models:
            table=model._meta.db_table
            fields={f.name:f for f in model._meta.fields}
            if 'brand' not in fields: continue
            conditions=[]
            for field in model._meta.fields:
                if field.is_relation and field.many_to_one and field.name!='brand':
                    target=field.remote_field.model
                    if any(f.name=='brand' for f in target._meta.fields):
                        conditions.append(f'(NEW.{field.column} IS NOT NULL AND NOT EXISTS (SELECT 1 FROM {target._meta.db_table} p WHERE p.id = NEW.{field.column} AND p.brand_id = NEW.brand_id))')
            condition=' OR '.join(conditions) or 'FALSE'
            if vendor=='sqlite':
                for operation in ('INSERT','UPDATE'):
                    cursor.execute(f"CREATE TRIGGER {table}_tenant_{operation.lower()} BEFORE {operation} ON {table} WHEN {condition} BEGIN SELECT RAISE(ABORT, 'Cross-brand relationship rejected'); END")
                cursor.execute(f"CREATE TRIGGER {table}_brand_guard BEFORE UPDATE ON {table} WHEN OLD.brand_id != NEW.brand_id BEGIN SELECT RAISE(ABORT, 'Brand relationship is immutable'); END")
            else:
                cursor.execute(f"CREATE FUNCTION {table}_tenant_guard() RETURNS trigger AS $$ BEGIN IF {condition} THEN RAISE EXCEPTION 'Cross-brand relationship rejected'; END IF; IF TG_OP = 'UPDATE' AND OLD.brand_id != NEW.brand_id THEN RAISE EXCEPTION 'Brand relationship is immutable'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql")
                cursor.execute(f"CREATE TRIGGER {table}_tenant BEFORE INSERT OR UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION {table}_tenant_guard()")
        for name in IMMUTABLE:
            table=apps.get_model('studio',name)._meta.db_table
            if vendor=='sqlite':
                for operation in ('UPDATE','DELETE'):
                    cursor.execute(f"CREATE TRIGGER {table}_immutable_{operation.lower()} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT, 'History is immutable'); END")
            else:
                cursor.execute(f"CREATE FUNCTION {table}_immutable_guard() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'History is immutable'; END; $$ LANGUAGE plpgsql")
                cursor.execute(f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION {table}_immutable_guard()")
        table='studio_asset'
        condition=' OR '.join(f'OLD.{field} IS DISTINCT FROM NEW.{field}' for field in ('storage_key','generation_id','original_id','width','height','mime_type','asset_type','source'))
        if vendor=='sqlite':
            cursor.execute(f"CREATE TRIGGER {table}_original_guard BEFORE UPDATE ON {table} WHEN {condition} BEGIN SELECT RAISE(ABORT, 'Original asset metadata is immutable'); END")
        else:
            cursor.execute(f"CREATE FUNCTION {table}_original_guard() RETURNS trigger AS $$ BEGIN IF {condition} THEN RAISE EXCEPTION 'Original asset metadata is immutable'; END IF; RETURN NEW; END; $$ LANGUAGE plpgsql")
            cursor.execute(f"CREATE TRIGGER {table}_original BEFORE UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION {table}_original_guard()")

def uninstall(apps,schema_editor):
    vendor=schema_editor.connection.vendor
    with schema_editor.connection.cursor() as cursor:
        for model in apps.get_app_config('studio').get_models():
            table=model._meta.db_table
            if vendor=='sqlite':
                for suffix in ('tenant_insert','tenant_update','brand_guard','immutable_update','immutable_delete','original_guard'):
                    cursor.execute(f'DROP TRIGGER IF EXISTS {table}_{suffix}')
            elif vendor=='postgresql':
                for suffix in ('tenant_guard','immutable_guard','original_guard'):
                    cursor.execute(f'DROP FUNCTION IF EXISTS {table}_{suffix}() CASCADE')

class Migration(migrations.Migration):
    dependencies=[('studio','0001_initial')]
    operations=[migrations.RunPython(install,uninstall)]
