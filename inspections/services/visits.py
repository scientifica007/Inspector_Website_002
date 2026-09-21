import uuid
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from inspections.models import Institution, Reference, Visit, VisitNode, Obligation
from .common import require_reference, draft_for_update, descendants, validate_parent, save_validated
from .references import snapshot


@transaction.atomic
def create_visit(actor, institution_id, date, reference_id=None):
    if not actor.is_authenticated:
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied
    institution = get_object_or_404(Institution, pk=institution_id, active=True)
    reference = get_object_or_404(Reference.objects.select_for_update(), pk=reference_id) if reference_id else None
    if reference:
        require_reference(actor, reference)
    material = snapshot(reference) if reference else {}
    visit = Visit(owner=actor, institution=institution, date=date,
        institution_snapshot={'id': institution.pk, 'name': institution.name, 'kind': institution.kind},
        inspector_snapshot={'id': actor.pk, 'username': actor.username, 'name': actor.get_full_name() or actor.username},
        source_reference_id=reference.pk if reference else None, reference_snapshot=material)
    # Empty JSON is a valid no-reference snapshot; do not use ModelForm's blank validation here.
    visit.full_clean(exclude=['reference_snapshot'])
    visit.save()
    VisitNode.objects.bulk_create([VisitNode(visit=visit, stable_id=n['id'], parent_stable_id=n['parent_id'],
        kind=n['kind'], title=n['title'], description=n['description'], position=n['position']) for n in material.get('nodes', [])])
    return visit


def constraints(visit):
    result = {n.pk: {'scope_locked': n.baseline_scope_locked, 'completion_required': n.baseline_completion_required,
                     'assignments': []} for n in visit.nodes.all()}
    obligations = Obligation.objects.filter(node__visit=visit, entry__assignment__status='ISSUED').select_related('entry__assignment')
    for o in obligations:
        current = result[o.node_id]
        current['scope_locked'] |= o.scope_locked
        current['completion_required'] |= o.completion_required
        aid = str(o.entry.assignment_id)
        if aid not in current['assignments']:
            current['assignments'].append(aid)
    for value in result.values():
        value['assignments'].sort()
    return result


def is_done(node):
    if node.kind == 'ITEM':
        return node.result in VisitNode.Result.values
    if node.kind == 'SPEC':
        return bool(node.value.strip())
    return False


def progress(visit):
    executable = [n for n in visit.nodes.all() if n.selected and n.state == 'ACTIVE' and n.kind != 'BRANCH']
    done, total = sum(is_done(n) for n in executable), len(executable)
    return {'done': done, 'total': total, 'percent': round(100 * done / total) if total else 0}


def scope_rows(visit, all_nodes=False):
    nodes = list(visit.nodes.all())
    by_id = {n.stable_id: n for n in nodes}
    wanted = {n.stable_id for n in nodes if n.selected}
    for n in nodes:
        if n.selected:
            parent, seen = n.parent_stable_id, set()
            while parent in by_id and parent not in seen:
                seen.add(parent)
                wanted.add(parent)
                parent = by_id[parent].parent_stable_id
    effective = constraints(visit)
    children = {}
    for n in nodes:
        children.setdefault(n.parent_stable_id, []).append(n)
    rows, stack = [], [(n, 0) for n in reversed(children.get(None, []))]
    while stack:
        n, depth = stack.pop()
        if all_nodes or n.stable_id in wanted:
            rows.append({'node': n, 'depth': min(depth, 5), 'context': not n.selected and n.stable_id in wanted,
                'effective': effective[n.pk], 'done': is_done(n)})
        stack.extend((child, depth + 1) for child in reversed(children.get(n.stable_id, [])))
    return rows


def select_nodes(visit, targets, origin):
    """Called only after actor authorization and while holding the visit lock."""
    nodes = list(visit.nodes.all())
    index = {str(n.stable_id): n for n in nodes}
    selected, added = {}, []
    for target_id in targets:
        if str(target_id) not in index:
            raise ValidationError('العنصر غير موجود في لقطة الزيارة.')
        for n in descendants(nodes, index[str(target_id)]):
            selected[n.pk] = n
    for n in selected.values():
        if not n.selected:
            n.selected = True
            if not n.origin:
                n.origin = origin
            added.append(str(n.stable_id))
        n.state = 'ACTIVE'
        n.save(update_fields=['selected', 'origin', 'state'])
        parent = index.get(str(n.parent_stable_id))
        while parent:
            if parent.selected and parent.state == 'EXCLUDED':
                parent.state = 'ACTIVE'
                parent.save(update_fields=['state'])
            parent = index.get(str(parent.parent_stable_id))
    return sorted(added)


@transaction.atomic
def select_scope(actor, visit_id, target_id):
    visit = draft_for_update(actor, visit_id)
    return select_nodes(visit, [target_id], 'MANUAL')


@transaction.atomic
def exclude_scope(actor, visit_id, target_id):
    visit = draft_for_update(actor, visit_id)
    nodes = list(visit.nodes.all())
    target = get_object_or_404(visit.nodes, stable_id=target_id)
    subtree = descendants(nodes, target)
    effective = constraints(visit)
    if any(effective[n.pk]['scope_locked'] for n in subtree):
        raise ValidationError('لا يمكن الاستبعاد: يتضمن النطاق عنصرًا مثبتًا بتكليف ساري أو قيد أصلي.')
    for n in subtree:
        if n.selected:
            n.state = 'EXCLUDED'
            n.save(update_fields=['state'])


@transaction.atomic
def restore_scope(actor, visit_id, target_id):
    visit = draft_for_update(actor, visit_id)
    nodes = list(visit.nodes.all())
    target = get_object_or_404(visit.nodes, stable_id=target_id, selected=True)
    index = {n.stable_id: n for n in nodes}
    restore = {n.pk: n for n in descendants(nodes, target) if n.selected}
    parent = index.get(target.parent_stable_id)
    while parent:
        if parent.selected:
            restore[parent.pk] = parent
        parent = index.get(parent.parent_stable_id)
    for n in restore.values():
        n.state = 'ACTIVE'
        n.save(update_fields=['state'])


@transaction.atomic
def write_local(actor, visit_id, *, kind, title, description='', parent_id=None, position=0, node_id=None):
    visit = draft_for_update(actor, visit_id)
    parent = get_object_or_404(visit.nodes, stable_id=parent_id) if parent_id else None
    validate_parent(kind, parent)
    node = get_object_or_404(visit.nodes, pk=node_id, local=True) if node_id else VisitNode(
        visit=visit, stable_id=uuid.uuid4(), local=True, selected=True, origin='LOCAL')
    if node_id and (node.kind != kind or node.parent_stable_id != (parent.stable_id if parent else None)):
        raise ValidationError('يمكن تحرير نص المحتوى المحلي؛ تغيير النوع أو الأب يحتاج عنصرًا جديدًا.')
    node.kind, node.title, node.description = kind, title.strip(), description
    node.parent_stable_id, node.position = parent.stable_id if parent else None, position
    save_validated(node)
    if parent and parent.selected and parent.state == 'EXCLUDED':
        restore_scope(actor, visit.pk, parent.stable_id)
    return node


@transaction.atomic
def record_result(actor, visit_id, node_id, *, result='', value='', observation=''):
    visit = draft_for_update(actor, visit_id)
    node = get_object_or_404(visit.nodes, pk=node_id, selected=True, state='ACTIVE')
    if node.kind == 'BRANCH':
        raise ValidationError('الفرع عقدة سياقية؛ سجل النتيجة في الوصف أو البند.')
    if result and (node.kind != 'ITEM' or result not in VisitNode.Result.values):
        raise ValidationError('نتيجة غير صالحة لهذا العنصر.')
    node.result = result if node.kind == 'ITEM' else ''
    node.value = value.strip() if node.kind == 'SPEC' else ''
    node.observation = observation
    return save_validated(node)


@transaction.atomic
def complete_visit(actor, visit_id):
    visit = draft_for_update(actor, visit_id)
    effective = constraints(visit)
    missing = [n.title for n in visit.nodes.all() if effective[n.pk]['completion_required']
        and (not n.selected or n.state != 'ACTIVE' or not is_done(n))]
    if missing:
        raise ValidationError('تعذر الإكمال. متطلبات إلزامية غير منجزة: ' + '، '.join(missing))
    # Administrative drafts have no legal effect and remain private after completion.
    visit.status, visit.completed_at = 'COMPLETED', timezone.now()
    from .exports import build_payload
    visit.completed_payload = build_payload(visit)
    visit.save(update_fields=['status', 'completed_at', 'completed_payload'])
    return visit


@transaction.atomic
def delete_draft(actor, visit_id):
    visit = draft_for_update(actor, visit_id)
    visit.delete()
