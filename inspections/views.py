from functools import wraps
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError, PermissionDenied
from django.db.models import Q
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST, require_http_methods
from . import forms
from .models import Institution, Reference, Visit, Guide, Assignment, Submission
from .services import references as refs, visits, governance as gov
from .services.common import require_admin, require_reference, require_visit, ordered_reference_nodes
from .services.exports import export_visit


def admin_only(view):
    @wraps(view)
    @login_required
    def wrapped(request, *args, **kwargs):
        require_admin(request.user)
        return view(request, *args, **kwargs)
    return wrapped


def error_text(error):
    return ' '.join(error.messages)


def form_page(request, form, title, cancel, description='', submit='حفظ'):
    return render(request, 'inspections/form.html', {'form': form, 'title': title, 'cancel': cancel, 'description': description, 'submit': submit})


@login_required
def dashboard(request):
    all_visits = request.user.is_admin and request.GET.get('all') == '1'
    qs = Visit.objects.all() if all_visits else Visit.objects.filter(owner=request.user)
    status = request.GET.get('status', '')
    if status in Visit.Status.values:
        qs = qs.filter(status=status)
    search = request.GET.get('q', '').strip()
    if search:
        qs = qs.filter(institution_snapshot__name__icontains=search)
    from django.core.paginator import Paginator
    page = Paginator(qs, 12).get_page(request.GET.get('page'))
    owned = Visit.objects.filter(owner=request.user)
    return render(request, 'inspections/dashboard.html', {'cards': [{'visit': v, 'progress': visits.progress(v)} for v in page], 'page': page, 'all_visits': all_visits,
        'drafts': owned.filter(status='DRAFT').count(), 'completed': owned.filter(status='COMPLETED').count(),
        'required': Assignment.objects.filter(visit__owner=request.user, visit__status='DRAFT', status='ISSUED').count(),
        'status_filter': status, 'search': search})


@login_required
def institutions(request):
    return render(request, 'inspections/institutions.html', {'institutions': Institution.objects.all()})


@admin_only
@require_http_methods(['GET', 'POST'])
def institution_edit(request, pk=None):
    instance = get_object_or_404(Institution, pk=pk) if pk else None
    form = forms.InstitutionForm(request.POST or None, instance=instance)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'حُفظت بيانات المؤسسة.')
        return redirect('institutions')
    return form_page(request, form, 'تحرير المؤسسة' if pk else 'إضافة مؤسسة', reverse('institutions'))


@login_required
def references(request):
    return render(request, 'inspections/references.html', {'references': Reference.objects.filter(Q(visibility='SHARED') | Q(owner=request.user))})


@login_required
@require_http_methods(['GET', 'POST'])
def reference_edit(request, pk=None):
    reference = get_object_or_404(Reference, pk=pk) if pk else None
    if reference:
        require_reference(request.user, reference, edit=True)
    form = forms.ReferenceForm(request.POST or None, actor=request.user, editing=bool(reference), initial={'title': reference.title, 'description': reference.description} if reference else {})
    if request.method == 'POST' and form.is_valid():
        try:
            d = form.cleaned_data
            reference = refs.update_reference(request.user, pk, d['title'], d['description']) if reference else refs.create_reference(request.user, d['title'], d['description'], d.get('shared', False))
            return redirect('reference_detail', pk=reference.pk)
        except ValidationError as error:
            form.add_error(None, error_text(error))
    return form_page(request, form, 'تحرير المرجع' if pk else 'إنشاء مرجع', reverse('references'))


@login_required
def reference_detail(request, pk):
    reference = get_object_or_404(Reference, pk=pk)
    require_reference(request.user, reference)
    editable = request.user.is_admin if reference.visibility == 'SHARED' else reference.owner_id == request.user.pk
    nodes, depths = ordered_reference_nodes(reference), {}
    for node in nodes:
        depths[node.pk] = depths.get(node.parent_id, -1) + 1
        node.depth = min(depths[node.pk], 5)
    return render(request, 'inspections/reference_detail.html', {'reference': reference, 'nodes': nodes, 'editable': editable})


@login_required
@require_http_methods(['GET', 'POST'])
def reference_node(request, pk, node_id=None):
    reference = get_object_or_404(Reference, pk=pk)
    require_reference(request.user, reference, edit=True)
    node = get_object_or_404(reference.nodes, pk=node_id) if node_id else None
    initial = {'kind': node.kind, 'title': node.title, 'description': node.description, 'position': node.position, 'parent_id': str(node.parent_id) if node.parent_id else ''} if node else {'parent_id': request.GET.get('parent', '')}
    form = forms.NodeForm(request.POST or None, nodes=reference.nodes.all(), initial=initial)
    if request.method == 'POST' and form.is_valid():
        try:
            refs.write_node(request.user, reference.pk, node_id=node_id, **form.cleaned_data)
            return redirect('reference_detail', pk=pk)
        except ValidationError as error:
            form.add_error(None, error_text(error))
    return form_page(request, form, 'تحرير عنصر المرجع' if node else 'إضافة عنصر للمرجع', reverse('reference_detail', args=[pk]))


@login_required
@require_http_methods(['GET', 'POST'])
def reference_action(request, pk, action, node_id=None):
    reference = get_object_or_404(Reference, pk=pk)
    require_reference(request.user, reference, edit=True)
    allowed = {'delete': 'حذف المرجع', 'submit': 'إرسال نسخة للمراجعة', 'delete_node': 'حذف العنصر وأبنائه'}
    if action not in allowed:
        return HttpResponseBadRequest()
    if node_id:
        get_object_or_404(reference.nodes, pk=node_id)
    if request.method == 'POST':
        try:
            if action == 'delete':
                refs.delete_reference(request.user, pk)
                return redirect('references')
            if action == 'submit':
                submission = refs.submit_reference(request.user, pk)
                return redirect('submission_detail', pk=submission.pk)
            refs.delete_node(request.user, pk, node_id)
            return redirect('reference_detail', pk=pk)
        except ValidationError as error:
            messages.error(request, error_text(error))
    detail = 'سترسل نسخة ثابتة للمراجعة. يبقى المرجع شخصيًا، ويمكنك مواصلة تحريره.' if action == 'submit' else 'سيزال المحتوى من المكتبة. لقطات الزيارات والاقتراحات السابقة تبقى محفوظة.'
    return render(request, 'inspections/confirm.html', {'title': allowed[action], 'description': detail, 'cancel': reverse('reference_detail', args=[pk]), 'danger': action != 'submit'})


@login_required
@require_http_methods(['GET', 'POST'])
def visit_create(request):
    form = forms.VisitForm(request.POST or None, actor=request.user, initial={'date': timezone.localdate()})
    if request.method == 'POST' and form.is_valid():
        d = form.cleaned_data
        try:
            visit = visits.create_visit(request.user, d['institution'].pk, d['date'], d['reference'].pk if d['reference'] else None)
            return redirect(reverse('visit_detail', args=[visit.pk]) + '?tab=scope')
        except ValidationError as error:
            form.add_error(None, error_text(error))
    return form_page(request, form, 'زيارة جديدة', reverse('dashboard'), 'ستحفظ الزيارة نسخة ثابتة من المرجع. اختر بعد ذلك عناصر نطاقك؛ يبدأ النطاق فارغًا.', 'إنشاء الزيارة')


@login_required
def visit_detail(request, pk):
    visit = get_object_or_404(Visit, pk=pk)
    require_visit(request.user, visit)
    tab = request.GET.get('tab', 'execute')
    if tab not in ['execute', 'scope', 'guides', 'assignments']:
        tab = 'execute'
    return render(request, 'inspections/visit_detail.html', {'visit': visit, 'editable': visit.owner_id == request.user.pk and visit.status == 'DRAFT', 'tab': tab,
        'rows': visits.scope_rows(visit), 'available': visits.scope_rows(visit, all_nodes=True), 'progress': visits.progress(visit),
        'guides': Guide.objects.filter(reference_id=visit.source_reference_id), 'applications': visit.guide_applications.all(), 'assignments': gov.visible_assignments(request.user, visit)})


@login_required
@require_POST
def visit_action(request, pk, action):
    visit = get_object_or_404(Visit, pk=pk)
    require_visit(request.user, visit, write=True)
    tab = 'execute' if action == 'save' else 'guides' if action == 'guide' else 'scope'
    form = forms.TargetForm(request.POST)
    if not form.is_valid():
        return HttpResponseBadRequest('معرّف عنصر غير صالح.')
    target = form.cleaned_data['target']
    try:
        if action == 'select':
            visits.select_scope(request.user, pk, target)
        elif action == 'exclude':
            visits.exclude_scope(request.user, pk, target)
        elif action == 'restore':
            visits.restore_scope(request.user, pk, target)
        elif action == 'guide':
            application, created = gov.apply_guide(request.user, pk, target)
            if created:
                messages.success(request, f'طُبق الدليل. عناصر أُضيفت: {len(application.added)}. عناصر غير موجودة في اللقطة جرى تخطيها: {len(application.skipped)}.')
            else:
                messages.info(request, 'هذه النسخة من الدليل مطبقة سابقًا؛ احتُفظ باختياراتك الحالية.')
        elif action == 'save':
            result_form = forms.ResultForm(request.POST)
            if not result_form.is_valid():
                return HttpResponseBadRequest('نتيجة غير صالحة. لم تحفظ البيانات.')
            visits.record_result(request.user, pk, target, **result_form.cleaned_data)
            messages.success(request, 'حُفظت النتيجة والملاحظة.')
        else:
            return HttpResponseBadRequest('عملية غير معروفة.')
    except ValidationError as error:
        messages.error(request, error_text(error))
    destination = reverse('visit_detail', args=[pk]) + '?tab=' + tab
    if action == 'save':
        destination += '#item-' + str(target)
    return redirect(destination)


@login_required
@require_http_methods(['GET', 'POST'])
def visit_finalize(request, pk, action):
    visit = get_object_or_404(Visit, pk=pk)
    require_visit(request.user, visit)
    if visit.owner_id != request.user.pk:
        raise PermissionDenied
    if action not in ['complete', 'delete']:
        return HttpResponseBadRequest()
    if visit.status != 'DRAFT':
        messages.error(request, 'الزيارة المكتملة لا تقبل التعديل أو الحذف.')
        return redirect('visit_detail', pk=pk)
    if request.method == 'POST':
        try:
            if action == 'delete':
                visits.delete_draft(request.user, pk)
                return redirect('dashboard')
            visits.complete_visit(request.user, pk)
            messages.success(request, 'أُكملت الزيارة وحُفظ سجلها التاريخي.')
            return redirect('visit_detail', pk=pk)
        except ValidationError as error:
            messages.error(request, error_text(error))
    p = visits.progress(visit)
    detail = 'ستُحذف المسودة ونتائجها وتكليفاتها. لا يمكن استرجاعها من التطبيق.' if action == 'delete' else f"المنجز {p['done']} من {p['total']}. سيصبح النطاق والنتائج نهائيين. يمنع الإكمال عند وجود متطلبات إلزامية غير منجزة."
    return render(request, 'inspections/confirm.html', {'title': 'حذف المسودة' if action == 'delete' else 'إكمال الزيارة', 'description': detail, 'cancel': reverse('visit_detail', args=[pk]), 'danger': action == 'delete'})


@login_required
@require_http_methods(['GET', 'POST'])
def visit_local(request, pk, node_id=None):
    visit = get_object_or_404(Visit, pk=pk)
    require_visit(request.user, visit, write=True)
    node = get_object_or_404(visit.nodes, pk=node_id, local=True) if node_id else None
    initial = {'kind': node.kind, 'title': node.title, 'description': node.description, 'position': node.position, 'parent_id': str(node.parent_stable_id) if node.parent_stable_id else ''} if node else {}
    form = forms.NodeForm(request.POST or None, nodes=visit.nodes.all(), local=True, initial=initial)
    if request.method == 'POST' and form.is_valid():
        try:
            visits.write_local(request.user, pk, node_id=node_id, **form.cleaned_data)
            return redirect(reverse('visit_detail', args=[pk]) + '?tab=scope')
        except ValidationError as error:
            form.add_error(None, error_text(error))
    return form_page(request, form, 'تحرير محتوى محلي' if node else 'إضافة محتوى محلي', reverse('visit_detail', args=[pk]), 'يبقى هذا المحتوى داخل الزيارة؛ لا يرسل للمراجعة ولا يغير المرجع.')


@login_required
def visit_export(request, pk):
    visit = get_object_or_404(Visit, pk=pk)
    response = HttpResponse(export_visit(request.user, visit), content_type='application/json; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="inspection-{visit.pk}.json"'
    response['Cache-Control'] = 'private, no-store'
    return response


@login_required
def guides(request):
    return render(request, 'inspections/guides.html', {'guides': Guide.objects.select_related('reference')})


@admin_only
@require_http_methods(['GET', 'POST'])
def guide_choose(request):
    form = forms.SharedReferenceForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        return redirect('guide_create', reference_id=form.cleaned_data['reference'].pk)
    return form_page(request, form, 'مرجع الدليل الجديد', reverse('guides'), submit='متابعة')


@admin_only
@require_http_methods(['GET', 'POST'])
def guide_edit(request, reference_id=None, pk=None):
    guide = get_object_or_404(Guide, pk=pk) if pk else None
    reference = get_object_or_404(Reference, pk=guide.reference_id if guide else reference_id, visibility='SHARED')
    form = forms.GuideForm(request.POST or None, nodes=ordered_reference_nodes(reference), initial={'title': guide.title, 'description': guide.description, 'targets': guide.targets} if guide else {})
    if request.method == 'POST' and form.is_valid():
        try:
            gov.write_guide(request.user, reference.pk, guide_id=pk, **form.cleaned_data)
            return redirect('guides')
        except ValidationError as error:
            form.add_error(None, error_text(error))
    return form_page(request, form, 'تحرير الدليل' if guide else 'إنشاء دليل اختياري', reverse('guides'), reference.title)


@admin_only
@require_http_methods(['GET', 'POST'])
def guide_delete(request, pk):
    get_object_or_404(Guide, pk=pk)
    if request.method == 'POST':
        gov.delete_guide(request.user, pk)
        return redirect('guides')
    return render(request, 'inspections/confirm.html', {'title': 'حذف الدليل', 'description': 'تطبيقات هذا الدليل المحفوظة في الزيارات لن تتغير.', 'cancel': reverse('guides'), 'danger': True})


@login_required
def submissions(request):
    qs = Submission.objects.all() if request.user.is_admin else Submission.objects.filter(owner=request.user)
    return render(request, 'inspections/submissions.html', {'submissions': qs.select_related('owner')})


@login_required
@require_http_methods(['GET', 'POST'])
def submission_detail(request, pk):
    submission = get_object_or_404(Submission, pk=pk)
    if not request.user.is_admin and submission.owner_id != request.user.pk:
        raise PermissionDenied
    form = forms.ReviewForm(request.POST or None)
    if request.method == 'POST':
        require_admin(request.user)
        if form.is_valid():
            try:
                refs.review_submission(request.user, pk, form.cleaned_data['decision'] == 'approve', form.cleaned_data['note'])
                return redirect('submission_detail', pk=pk)
            except ValidationError as error:
                form.add_error(None, error_text(error))
    return render(request, 'inspections/submission_detail.html', {'submission': submission, 'form': form})


@login_required
def assignments(request):
    qs = Assignment.objects.select_related('visit')
    if not request.user.is_admin:
        qs = qs.filter(visit__owner=request.user).exclude(status='DRAFT')
    return render(request, 'inspections/assignments.html', {'assignments': qs})


@admin_only
@require_http_methods(['GET', 'POST'])
def assignment_choose(request):
    form = forms.AssignmentVisitForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        return redirect('assignment_create', visit_id=form.cleaned_data['visit'].pk)
    return form_page(request, form, 'زيارة التكليف الجديد', reverse('assignments'), submit='متابعة')


@admin_only
@require_http_methods(['GET', 'POST'])
def assignment_edit(request, visit_id=None, pk=None):
    assignment = get_object_or_404(Assignment, pk=pk) if pk else None
    visit = get_object_or_404(Visit, pk=assignment.visit_id if assignment else visit_id)
    if visit.status != 'DRAFT' or (assignment and assignment.status != 'DRAFT'):
        messages.error(request, 'لا يمكن تحرير التكليف في هذه الحالة.')
        return redirect('assignments')
    entries = {str(e.target_stable_id): {'scope_locked': e.scope_locked, 'completion_required': e.completion_required} for e in assignment.entries.all()} if assignment else {}
    form = forms.AssignmentForm(request.POST or None, visit=visit, entries=entries, initial={'title': assignment.title} if assignment else {})
    if request.method == 'POST' and form.is_valid():
        try:
            assignment = gov.write_assignment(request.user, visit.pk, form.cleaned_data['title'], form.entries, pk)
            return redirect('assignment_detail', pk=assignment.pk)
        except ValidationError as error:
            form.add_error(None, error_text(error))
    return render(request, 'inspections/assignment_form.html', {'form': form, 'visit': visit})


@login_required
def assignment_detail(request, pk):
    assignment = get_object_or_404(Assignment.objects.select_related('visit'), pk=pk)
    require_visit(request.user, assignment.visit)
    if assignment.status == 'DRAFT' and not request.user.is_admin:
        raise PermissionDenied
    nodes = {n['id']: n for n in assignment.visit.reference_snapshot.get('nodes', [])}
    rows = [{'entry': e, 'node': nodes.get(str(e.target_stable_id), {'title': 'هدف غير صالح'})} for e in assignment.entries.all()]
    return render(request, 'inspections/assignment_detail.html', {'assignment': assignment, 'rows': rows})


@admin_only
@require_http_methods(['GET', 'POST'])
def assignment_issue(request, pk):
    get_object_or_404(Assignment, pk=pk)
    if request.method == 'POST':
        try:
            gov.issue_assignment(request.user, pk)
            messages.success(request, 'صدر التكليف وأصبح ظاهرًا لصاحب الزيارة.')
        except ValidationError as error:
            messages.error(request, error_text(error))
        return redirect('assignment_detail', pk=pk)
    return render(request, 'inspections/confirm.html', {'title': 'إصدار التكليف رسميًا', 'description': 'ستضاف الالتزامات إلى الزيارة دفعة واحدة. بعد الإصدار لا يمكن تحرير المحتوى؛ الإلغاء يحتاج سببًا مسجلًا.', 'cancel': reverse('assignment_detail', args=[pk])})


@admin_only
@require_http_methods(['GET', 'POST'])
def assignment_revoke(request, pk):
    get_object_or_404(Assignment, pk=pk)
    form = forms.ReasonForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            gov.revoke_assignment(request.user, pk, form.cleaned_data['reason'])
            return redirect('assignment_detail', pk=pk)
        except ValidationError as error:
            form.add_error(None, error_text(error))
    return form_page(request, form, 'إلغاء التكليف', reverse('assignment_detail', args=[pk]), 'تبقى العناصر والنتائج محفوظة. تزول فقط الالتزامات التي يفرضها هذا التكليف.', 'تسجيل الإلغاء')
