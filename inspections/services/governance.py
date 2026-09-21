import hashlib
import json
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from inspections.models import Reference, Guide, GuideApplication, Assignment, AssignmentEntry, Obligation
from .common import require_admin, require_visit, draft_for_update, descendants, save_validated
from .visits import select_nodes


@transaction.atomic
def write_guide(actor, reference_id, title, description, targets, guide_id=None):
    require_admin(actor)
    reference = get_object_or_404(Reference.objects.select_for_update(), pk=reference_id, visibility='SHARED')
    valid = {str(v) for v in reference.nodes.values_list('pk', flat=True)}
    targets = sorted(set(str(v) for v in targets))
    if not targets or not set(targets).issubset(valid):
        raise ValidationError('اختر عناصر موجودة في المرجع المشترك.')
    guide = get_object_or_404(Guide.objects.select_for_update(), pk=guide_id) if guide_id else Guide()
    if guide_id and guide.reference_id != reference.pk:
        raise ValidationError('لا يمكن تغيير مرجع دليل موجود.')
    guide.reference, guide.title, guide.description, guide.targets = reference, title.strip(), description, targets
    return save_validated(guide)


@transaction.atomic
def delete_guide(actor, guide_id):
    require_admin(actor)
    get_object_or_404(Guide.objects.select_for_update(), pk=guide_id).delete()


@transaction.atomic
def apply_guide(actor, visit_id, guide_id):
    visit = draft_for_update(actor, visit_id)
    guide = get_object_or_404(Guide.objects.select_for_update(), pk=guide_id)
    if guide.reference_id != visit.source_reference_id:
        raise ValidationError('الدليل لا يخص المرجع الذي جُمّدت منه هذه الزيارة.')
    material = {'id': str(guide.pk), 'reference_id': str(guide.reference_id), 'title': guide.title,
        'description': guide.description, 'targets': sorted(set(guide.targets))}
    fingerprint = hashlib.sha256(json.dumps(material, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    previous = GuideApplication.objects.filter(visit=visit, guide_id=guide.pk, fingerprint=fingerprint).first()
    if previous:
        return previous, False
    valid = {n['id'] for n in visit.reference_snapshot.get('nodes', [])}
    compatible = [v for v in material['targets'] if v in valid]
    skipped = [v for v in material['targets'] if v not in valid]
    added = select_nodes(visit, compatible, 'GUIDE')
    return GuideApplication.objects.create(visit=visit, guide_id=guide.pk, fingerprint=fingerprint,
        snapshot=material, applied_by=actor, added=added, skipped=skipped), True


@transaction.atomic
def write_assignment(actor, visit_id, title, entries, assignment_id=None):
    visit = draft_for_update(actor, visit_id, administrative=True)
    assignment = get_object_or_404(Assignment.objects.select_for_update(), pk=assignment_id, visit=visit) if assignment_id else Assignment(visit=visit, created_by=actor)
    if assignment.status != 'DRAFT':
        raise ValidationError('التكليف الصادر سجل رسمي؛ لا يقبل تحرير المحتوى.')
    valid = {n['id'] for n in visit.reference_snapshot.get('nodes', [])}
    seen = set()
    if not entries:
        raise ValidationError('أضف عنصرًا واحدًا على الأقل إلى التكليف.')
    for entry in entries:
        target = str(entry['target_stable_id'])
        if target not in valid or target in seen:
            raise ValidationError('هدف مكرر أو غير موجود في لقطة الزيارة.')
        if not (entry.get('scope_locked') or entry.get('completion_required')):
            raise ValidationError('حدد تثبيت النطاق أو اشتراط الإنجاز لكل هدف.')
        seen.add(target)
    assignment.title = title.strip()
    save_validated(assignment)
    assignment.entries.all().delete()
    AssignmentEntry.objects.bulk_create([AssignmentEntry(assignment=assignment, **entry) for entry in entries])
    return assignment


@transaction.atomic
def issue_assignment(actor, assignment_id):
    # Lock order is always Visit -> Assignment, also for edit, completion and revoke.
    require_admin(actor)
    visit_id = get_object_or_404(Assignment, pk=assignment_id).visit_id
    visit = draft_for_update(actor, visit_id, administrative=True)
    assignment = get_object_or_404(Assignment.objects.select_for_update(), pk=assignment_id)
    if assignment.status != 'DRAFT':
        raise ValidationError('لا يمكن إصدار هذا التكليف مرتين.')
    entries = list(assignment.entries.all())
    nodes = list(visit.nodes.all())
    index = {str(n.stable_id): n for n in nodes}
    frozen_ids = {n['id'] for n in visit.reference_snapshot.get('nodes', [])}
    if not entries:
        raise ValidationError('التكليف فارغ.')
    expanded = []
    for entry in entries:
        target = str(entry.target_stable_id)
        if target not in frozen_ids or target not in index or not (entry.scope_locked or entry.completion_required):
            raise ValidationError('الإصدار مرفوض بالكامل: أحد الأهداف غير صالح.')
        # Scope of legal obligations is the frozen reference subtree, never later local additions.
        subtree = [n for n in descendants(nodes, index[target]) if str(n.stable_id) in frozen_ids]
        for node in subtree:
            expanded.append(Obligation(entry=entry, node=node, scope_locked=entry.scope_locked,
                completion_required=entry.completion_required and node.kind != 'BRANCH'))
    # Validation of every entry has finished before any visit write.
    for obligation in expanded:
        node = obligation.node
        if not node.selected:
            node.selected = True
            if not node.origin:
                node.origin = 'ASSIGNMENT'
        node.state = 'ACTIVE'
        node.save(update_fields=['selected', 'origin', 'state'])
        parent = index.get(str(node.parent_stable_id))
        while parent:
            if parent.selected and parent.state == 'EXCLUDED':
                parent.state = 'ACTIVE'
                parent.save(update_fields=['state'])
            parent = index.get(str(parent.parent_stable_id))
    Obligation.objects.bulk_create(expanded)
    assignment.status, assignment.issued_by, assignment.issued_at = 'ISSUED', actor, timezone.now()
    assignment.save(update_fields=['status', 'issued_by', 'issued_at'])
    return assignment


@transaction.atomic
def revoke_assignment(actor, assignment_id, reason):
    require_admin(actor)
    visit_id = get_object_or_404(Assignment, pk=assignment_id).visit_id
    draft_for_update(actor, visit_id, administrative=True)
    assignment = get_object_or_404(Assignment.objects.select_for_update(), pk=assignment_id)
    if assignment.status != 'ISSUED':
        raise ValidationError('يمكن إلغاء تكليف صادر فقط.')
    if not reason.strip():
        raise ValidationError('سبب الإلغاء إلزامي.')
    assignment.status, assignment.revoked_by, assignment.revoked_at = 'REVOKED', actor, timezone.now()
    assignment.revocation_reason = reason.strip()
    assignment.save(update_fields=['status', 'revoked_by', 'revoked_at', 'revocation_reason'])
    return assignment


def visible_assignments(actor, visit):
    require_visit(actor, visit)
    assignments = visit.assignments.all()
    return assignments if actor.is_admin else assignments.exclude(status='DRAFT')
