"""Database defense against accidental ORM/bulk mutation of completed history.

No data transformation. Guards apply equally to SQLite and PostgreSQL.
"""
from django.db import migrations


CHILDREN = {
    'visitnode': 'SELECT status FROM inspections_visit WHERE id = {row}.visit_id',
    'assignment': 'SELECT status FROM inspections_visit WHERE id = {row}.visit_id',
    'guideapplication': 'SELECT status FROM inspections_visit WHERE id = {row}.visit_id',
    'assignmententry': 'SELECT v.status FROM inspections_visit v JOIN inspections_assignment a ON a.visit_id=v.id WHERE a.id={row}.assignment_id',
    'obligation': 'SELECT v.status FROM inspections_visit v JOIN inspections_visitnode n ON n.visit_id=v.id WHERE n.id={row}.node_id',
}


def definitions(vendor):
    null_diff = (lambda field: f'OLD.{field} IS NOT NEW.{field}') if vendor == 'sqlite' else (lambda field: f'OLD.{field}::text IS DISTINCT FROM NEW.{field}::text')
    rules = [('visit_sealed_update', 'visit', 'UPDATE', "OLD.status = 'COMPLETED'"),
             ('visit_sealed_delete', 'visit', 'DELETE', "OLD.status = 'COMPLETED'")]
    frozen = ['owner_id', 'institution_id', 'institution_snapshot', 'inspector_snapshot', 'source_reference_id', 'reference_snapshot', 'date', 'created_at']
    rules.append(('visit_source_frozen', 'visit', 'UPDATE', '(' + ' OR '.join(null_diff(f) for f in frozen) + ')'))
    node_frozen = ['visit_id', 'stable_id', 'parent_stable_id', 'kind', 'title', 'description', 'position', 'local']
    rules.append(('node_source_frozen', 'visitnode', 'UPDATE', "NOT OLD.local AND (" + ' OR '.join(null_diff(f) for f in node_frozen) + ')'))
    rules.append(('node_origin_retained', 'visitnode', 'UPDATE', "OLD.origin <> '' AND (" + null_diff('origin') + ')'))
    rules.append(('submission_material_frozen', 'submission', 'UPDATE', '(' + ' OR '.join(null_diff(f) for f in ['owner_id', 'source_id', 'snapshot', 'submitted_at']) + ')'))
    for table, query in CHILDREN.items():
        for event in ['INSERT', 'UPDATE', 'DELETE']:
            rows = ['NEW'] if event == 'INSERT' else ['OLD'] if event == 'DELETE' else ['OLD', 'NEW']
            condition = ' OR '.join(f"({query.format(row=row)}) = 'COMPLETED'" for row in rows)
            rules.append((f'{table}_sealed_{event.lower()}', table, event, condition))
    return rules


def install(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    if vendor not in ('sqlite', 'postgresql'):
        raise RuntimeError('Historical guards support SQLite and PostgreSQL only.')
    for name, table, event, condition in definitions(vendor):
        if vendor == 'sqlite':
            schema_editor.execute(f"CREATE TRIGGER {name} BEFORE {event} ON inspections_{table} WHEN {condition} BEGIN SELECT RAISE(ABORT, 'historical_record_immutable'); END;")
        else:
            returned = 'OLD' if event == 'DELETE' else 'NEW'
            schema_editor.execute(f"CREATE FUNCTION {name}_fn() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF {condition} THEN RAISE EXCEPTION 'historical_record_immutable' USING ERRCODE='23514'; END IF; RETURN {returned}; END; $$;")
            schema_editor.execute(f"CREATE TRIGGER {name} BEFORE {event} ON inspections_{table} FOR EACH ROW EXECUTE FUNCTION {name}_fn();")


def uninstall(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    for name, table, _, _ in definitions(vendor):
        if vendor == 'sqlite':
            schema_editor.execute(f'DROP TRIGGER IF EXISTS {name};')
        elif vendor == 'postgresql':
            schema_editor.execute(f'DROP TRIGGER IF EXISTS {name} ON inspections_{table};')
            schema_editor.execute(f'DROP FUNCTION IF EXISTS {name}_fn();')


class Migration(migrations.Migration):
    dependencies = [('inspections', '0001_initial')]
    operations = [migrations.RunPython(install, uninstall)]
