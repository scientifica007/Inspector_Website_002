from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404
from inspections.models import Reference, Visit


def require_admin(actor):
    if not actor.is_authenticated or not actor.is_admin:
        raise PermissionDenied('هذه العملية مخصصة للإدارة.')


def can_read_reference(actor, reference):
    return actor.is_authenticated and (reference.visibility == 'SHARED' or reference.owner_id == actor.pk)


def require_reference(actor, reference, edit=False):
    allowed = can_read_reference(actor, reference)
    if edit:
        allowed = allowed and (actor.is_admin if reference.visibility == 'SHARED' else reference.owner_id == actor.pk)
    if not allowed:
        raise PermissionDenied('لا تملك صلاحية الوصول إلى هذا المرجع.')


def require_visit(actor, visit, write=False):
    if not actor.is_authenticated or (visit.owner_id != actor.pk and (write or not actor.is_admin)):
        raise PermissionDenied('الزيارة ليست ضمن صلاحياتك.')
    if write and visit.status != Visit.Status.DRAFT:
        raise ValidationError('الزيارة المكتملة محفوظة ولا تقبل التعديل.')


def draft_for_update(actor, visit_id, administrative=False):
    visit = get_object_or_404(Visit.objects.select_for_update(), pk=visit_id)
    if administrative:
        require_admin(actor)
        if visit.status != Visit.Status.DRAFT:
            raise ValidationError('لا يمكن تغيير تكليفات زيارة مكتملة.')
    else:
        require_visit(actor, visit, write=True)
    return visit


def descendants(nodes, target):
    """Iterative traversal; stable ordering and no recursion depth dependency."""
    by_parent = {}
    for node in nodes:
        parent = str(node.parent_stable_id or '')
        by_parent.setdefault(parent, []).append(node)
    found, stack, seen = [], [target], set()
    while stack:
        node = stack.pop()
        if node.stable_id in seen:
            raise ValidationError('حلقة غير صالحة في الشجرة.')
        seen.add(node.stable_id)
        found.append(node)
        stack.extend(reversed(by_parent.get(str(node.stable_id), [])))
    return found


def ordered_reference_nodes(reference):
    nodes = list(reference.nodes.all())
    by_parent = {}
    for node in nodes:
        by_parent.setdefault(node.parent_id, []).append(node)
    result, stack = [], list(reversed(by_parent.get(None, [])))
    while stack:
        node = stack.pop()
        result.append(node)
        stack.extend(reversed(by_parent.get(node.pk, [])))
    if len(result) != len(nodes):
        raise ValidationError('بنية المرجع غير صالحة.')
    return result


def validate_parent(kind, parent):
    if parent and (parent.kind == 'ITEM' or (kind in ('BRANCH', 'SPEC') and parent.kind != 'BRANCH')):
        raise ValidationError('الأب غير ملائم لنوع العنصر.')


def save_validated(obj):
    obj.full_clean()
    obj.save()
    return obj
