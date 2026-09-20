import uuid
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from inspections.models import Reference, ReferenceNode, Submission
from .common import require_admin, require_reference, validate_parent, ordered_reference_nodes, save_validated


def snapshot(reference):
    return {'schema_version': 1, 'id': str(reference.pk), 'title': reference.title,
        'description': reference.description, 'visibility': reference.visibility,
        'owner_id': reference.owner_id, 'created_at': reference.created_at.isoformat(),
        'updated_at': reference.updated_at.isoformat(), 'provenance': reference.provenance,
        'nodes': [{'id': str(n.pk), 'parent_id': str(n.parent_id) if n.parent_id else None,
            'kind': n.kind, 'title': n.title, 'description': n.description, 'position': n.position}
            for n in ordered_reference_nodes(reference)]}


@transaction.atomic
def create_reference(actor, title, description='', shared=False):
    if shared:
        require_admin(actor)
    elif not actor.is_authenticated:
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied
    return save_validated(Reference(title=title.strip(), description=description,
        owner=actor, visibility='SHARED' if shared else 'PRIVATE'))


@transaction.atomic
def update_reference(actor, reference_id, title, description):
    reference = get_object_or_404(Reference.objects.select_for_update(), pk=reference_id)
    require_reference(actor, reference, edit=True)
    reference.title, reference.description = title.strip(), description
    return save_validated(reference)


@transaction.atomic
def delete_reference(actor, reference_id):
    reference = get_object_or_404(Reference.objects.select_for_update(), pk=reference_id)
    require_reference(actor, reference, edit=True)
    reference.delete()


@transaction.atomic
def write_node(actor, reference_id, *, kind, title, description='', parent_id=None, position=0, node_id=None):
    reference = get_object_or_404(Reference.objects.select_for_update(), pk=reference_id)
    require_reference(actor, reference, edit=True)
    node = get_object_or_404(reference.nodes, pk=node_id) if node_id else ReferenceNode(reference=reference)
    parent = get_object_or_404(reference.nodes, pk=parent_id) if parent_id else None
    validate_parent(kind, parent)
    cursor = parent
    while cursor:
        if cursor.pk == node.pk:
            raise ValidationError('لا يمكن جعل العنصر أبًا لنفسه أو لأحد أسلافه.')
        cursor = cursor.parent
    if node_id and node.kind != kind and node.children.exists():
        raise ValidationError('لا يمكن تغيير نوع عنصر له أبناء؛ حرر عنوانه أو أنشئ عنصرًا جديدًا.')
    node.kind, node.title, node.description = kind, title.strip(), description
    node.parent, node.position = parent, position
    save_validated(node)
    reference.save(update_fields=['updated_at'])
    return node


@transaction.atomic
def delete_node(actor, reference_id, node_id):
    reference = get_object_or_404(Reference.objects.select_for_update(), pk=reference_id)
    require_reference(actor, reference, edit=True)
    get_object_or_404(reference.nodes, pk=node_id).delete()
    reference.save(update_fields=['updated_at'])


@transaction.atomic
def submit_reference(actor, reference_id):
    reference = get_object_or_404(Reference.objects.select_for_update(), pk=reference_id)
    require_reference(actor, reference, edit=True)
    if reference.visibility != 'PRIVATE':
        raise ValidationError('الإرسال للمراجعة خاص بالمراجع الشخصية.')
    material = snapshot(reference)
    if not material['nodes']:
        raise ValidationError('أضف محتوى إلى المرجع قبل إرساله.')
    pending = Submission.objects.filter(owner=actor, source_id=reference.pk, status='PENDING')
    if any(s.snapshot == material for s in pending):
        raise ValidationError('هذه النسخة أُرسلت وهي قيد المراجعة.')
    return Submission.objects.create(owner=actor, source_id=reference.pk, snapshot=material)


@transaction.atomic
def review_submission(actor, submission_id, accept, note=''):
    require_admin(actor)
    submission = get_object_or_404(Submission.objects.select_for_update(), pk=submission_id)
    if submission.status != 'PENDING':
        raise ValidationError('سبق اتخاذ قرار بشأن هذا الاقتراح.')
    if accept:
        source = submission.snapshot
        mapping = {n['id']: uuid.uuid4() for n in source['nodes']}
        reference = Reference.objects.create(title=source['title'], description=source['description'],
            visibility='SHARED', owner=actor, provenance={'submission_id': str(submission.pk),
            'source_reference_id': source['id'], 'source_owner_id': submission.owner_id,
            'stable_id_map': {key: str(value) for key, value in mapping.items()}})
        for n in source['nodes']:
            ReferenceNode.objects.create(id=mapping[n['id']], reference=reference,
                parent_id=mapping.get(n['parent_id']), kind=n['kind'], title=n['title'],
                description=n['description'], position=n['position'])
        submission.published_reference_id = reference.pk
    submission.status = 'APPROVED' if accept else 'REJECTED'
    submission.reviewer, submission.reviewed_at, submission.review_note = actor, timezone.now(), note
    submission.save()
    return submission
