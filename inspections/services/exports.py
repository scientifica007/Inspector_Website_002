import json
from inspections.models import Visit
from .common import require_visit
from .visits import constraints, progress, scope_rows


def stamp(value):
    return value.isoformat() if value else None


def build_payload(visit):
    effective = constraints(visit)
    context_ids = {str(r['node'].stable_id) for r in scope_rows(visit) if r['context']}
    assignments = []
    # Unissued administrative drafts never leak into the inspector's data/export.
    for assignment in visit.assignments.exclude(status='DRAFT'):
        assignments.append({'id': str(assignment.pk), 'title': assignment.title, 'status': assignment.status,
            'created_by_id': assignment.created_by_id, 'created_at': stamp(assignment.created_at),
            'issued_by_id': assignment.issued_by_id, 'issued_at': stamp(assignment.issued_at),
            'revoked_by_id': assignment.revoked_by_id, 'revoked_at': stamp(assignment.revoked_at),
            'revocation_reason': assignment.revocation_reason,
            'entries': [{'target_stable_id': str(e.target_stable_id), 'scope_locked': e.scope_locked,
                'completion_required': e.completion_required,
                'expanded_obligations': [{'node_stable_id': str(o.node.stable_id),
                    'scope_locked': o.scope_locked, 'completion_required': o.completion_required}
                    for o in e.obligations.select_related('node').order_by('node__stable_id')]}
                for e in assignment.entries.all()]})
    return {'schema': 'inspector-visit', 'schema_version': 1,
        'visit': {'id': str(visit.pk), 'date': visit.date.isoformat(), 'status': visit.status,
            'created_at': stamp(visit.created_at), 'completed_at': stamp(visit.completed_at)},
        'institution': visit.institution_snapshot, 'inspector': visit.inspector_snapshot,
        'reference_snapshot': visit.reference_snapshot, 'progress': progress(visit),
        'nodes': [{'id': str(n.pk), 'stable_id': str(n.stable_id),
            'parent_stable_id': str(n.parent_stable_id) if n.parent_stable_id else None,
            'kind': n.kind, 'title': n.title, 'description': n.description, 'position': n.position,
            'scope_role': 'SELECTED' if n.selected else ('CONTEXT' if str(n.stable_id) in context_ids else 'AVAILABLE'),
            'state': n.state, 'origin': n.origin or None, 'local': n.local,
            'baseline': {'scope_locked': n.baseline_scope_locked, 'completion_required': n.baseline_completion_required},
            'effective': effective[n.pk], 'result': n.result or None, 'value': n.value,
            'observation': n.observation} for n in visit.nodes.order_by('position', 'stable_id')],
        'guide_applications': [{'guide_id': str(a.guide_id), 'fingerprint': a.fingerprint,
            'snapshot': a.snapshot, 'applied_by_id': a.applied_by_id, 'applied_at': stamp(a.applied_at),
            'added': a.added, 'skipped': a.skipped} for a in visit.guide_applications.all()],
        'assignments': assignments}


def export_visit(actor, visit):
    require_visit(actor, visit)
    payload = visit.completed_payload if visit.status == Visit.Status.COMPLETED else build_payload(visit)
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + '\n'
