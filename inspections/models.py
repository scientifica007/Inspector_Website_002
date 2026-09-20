import uuid
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = 'ADMIN', 'إدارة'
        INSPECTOR = 'INSPECTOR', 'مفتش'
    role = models.CharField(max_length=12, choices=Role.choices, default=Role.INSPECTOR)

    @property
    def is_admin(self):
        return self.is_authenticated and (self.role == self.Role.ADMIN or self.is_superuser)

    def save(self, *args, **kwargs):
        if self.is_superuser:
            self.role = self.Role.ADMIN
        super().save(*args, **kwargs)


class Institution(models.Model):
    name = models.CharField('اسم المؤسسة', max_length=240)
    kind = models.CharField('النوع', max_length=100, blank=True)
    active = models.BooleanField('نشطة', default=True)
    class Meta:
        ordering = ['name', 'pk']
    def __str__(self):
        return self.name


class Reference(models.Model):
    class Visibility(models.TextChoices):
        SHARED = 'SHARED', 'مشترك'
        PRIVATE = 'PRIVATE', 'شخصي'
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField('اسم المرجع', max_length=240)
    description = models.TextField('تعريف المرجع', blank=True)
    visibility = models.CharField(max_length=8, choices=Visibility.choices)
    owner = models.ForeignKey(User, on_delete=models.PROTECT, related_name='references')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    provenance = models.JSONField(default=dict, blank=True)
    class Meta:
        ordering = ['title', 'id']
    def __str__(self):
        return self.title


class NodeKind(models.TextChoices):
    BRANCH = 'BRANCH', 'فرع'
    SPEC = 'SPEC', 'وصف / مواصفة'
    ITEM = 'ITEM', 'بند فحص'


class ReferenceNode(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reference = models.ForeignKey(Reference, on_delete=models.CASCADE, related_name='nodes')
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE, related_name='children')
    kind = models.CharField('نوع العنصر', max_length=8, choices=NodeKind.choices)
    title = models.CharField('العنوان', max_length=300)
    description = models.TextField('التوضيح', blank=True)
    position = models.PositiveIntegerField(default=0)
    class Meta:
        ordering = ['position', 'id']


class Submission(models.Model):
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'قيد المراجعة'
        APPROVED = 'APPROVED', 'مقبول'
        REJECTED = 'REJECTED', 'مرفوض'
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(User, on_delete=models.PROTECT)
    source_id = models.UUIDField()
    snapshot = models.JSONField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    submitted_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewer = models.ForeignKey(User, null=True, blank=True, on_delete=models.PROTECT, related_name='reviews')
    review_note = models.TextField(blank=True)
    published_reference_id = models.UUIDField(null=True, blank=True)
    class Meta:
        ordering = ['-submitted_at', 'id']


class Visit(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'مسودة'
        COMPLETED = 'COMPLETED', 'مكتملة'
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(User, on_delete=models.PROTECT, related_name='visits')
    institution = models.ForeignKey(Institution, on_delete=models.PROTECT)
    institution_snapshot = models.JSONField()
    inspector_snapshot = models.JSONField()
    date = models.DateField('تاريخ الزيارة')
    source_reference_id = models.UUIDField(null=True, blank=True)
    reference_snapshot = models.JSONField(default=dict)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_payload = models.JSONField(null=True, blank=True)
    class Meta:
        ordering = ['-date', '-created_at', 'id']
        constraints = [models.CheckConstraint(
            condition=(models.Q(status='DRAFT', completed_at__isnull=True, completed_payload__isnull=True) |
                       models.Q(status='COMPLETED', completed_at__isnull=False, completed_payload__isnull=False)),
            name='visit_completion_sealed')]


class VisitNode(models.Model):
    class Origin(models.TextChoices):
        LEGACY = 'LEGACY', 'موروث'
        MANUAL = 'MANUAL', 'اختيار المفتش'
        GUIDE = 'GUIDE', 'دليل اختياري'
        ASSIGNMENT = 'ASSIGNMENT', 'تكليف رسمي'
        LOCAL = 'LOCAL', 'محتوى محلي'
    class State(models.TextChoices):
        ACTIVE = 'ACTIVE', 'نشط'
        EXCLUDED = 'EXCLUDED', 'مستبعد'
    class Result(models.TextChoices):
        CONFORMING = 'CONFORMING', 'مطابق'
        NONCONFORMING = 'NONCONFORMING', 'غير مطابق'
        NOT_APPLICABLE = 'NOT_APPLICABLE', 'غير منطبق'
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    visit = models.ForeignKey(Visit, on_delete=models.CASCADE, related_name='nodes')
    stable_id = models.UUIDField(default=uuid.uuid4)
    parent_stable_id = models.UUIDField(null=True, blank=True)
    kind = models.CharField(max_length=8, choices=NodeKind.choices)
    title = models.CharField(max_length=300)
    description = models.TextField(blank=True)
    position = models.PositiveIntegerField(default=0)
    selected = models.BooleanField(default=False)
    state = models.CharField(max_length=8, choices=State.choices, default=State.ACTIVE)
    origin = models.CharField(max_length=12, choices=Origin.choices, blank=True)
    local = models.BooleanField(default=False)
    baseline_scope_locked = models.BooleanField(default=False)
    baseline_completion_required = models.BooleanField(default=False)
    result = models.CharField(max_length=16, choices=Result.choices, blank=True)
    value = models.TextField(blank=True)
    observation = models.TextField(blank=True)
    class Meta:
        ordering = ['position', 'stable_id']
        constraints = [
            models.UniqueConstraint(fields=['visit', 'stable_id'], name='unique_visit_stable_node'),
            models.CheckConstraint(condition=models.Q(selected=False) | ~models.Q(origin=''), name='selected_node_has_origin'),
            models.CheckConstraint(condition=models.Q(kind='ITEM') | models.Q(result=''), name='result_only_on_items'),
            models.CheckConstraint(condition=~models.Q(kind='BRANCH') | models.Q(baseline_completion_required=False), name='branch_not_completable'),
        ]


class Guide(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reference = models.ForeignKey(Reference, on_delete=models.CASCADE, related_name='guides')
    title = models.CharField('اسم الدليل', max_length=240)
    description = models.TextField('وصف الدليل', blank=True)
    targets = models.JSONField(default=list)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        ordering = ['title', 'id']


class GuideApplication(models.Model):
    visit = models.ForeignKey(Visit, on_delete=models.CASCADE, related_name='guide_applications')
    guide_id = models.UUIDField()
    fingerprint = models.CharField(max_length=64)
    snapshot = models.JSONField()
    applied_by = models.ForeignKey(User, on_delete=models.PROTECT)
    applied_at = models.DateTimeField(auto_now_add=True)
    added = models.JSONField(default=list)
    skipped = models.JSONField(default=list)
    class Meta:
        ordering = ['applied_at', 'pk']
        constraints = [models.UniqueConstraint(fields=['visit', 'guide_id', 'fingerprint'], name='unique_guide_application')]


class Assignment(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'مسودة إدارية'
        ISSUED = 'ISSUED', 'صادر'
        REVOKED = 'REVOKED', 'ملغى'
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    visit = models.ForeignKey(Visit, on_delete=models.CASCADE, related_name='assignments')
    title = models.CharField('عنوان التكليف', max_length=240)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.DRAFT)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='created_assignments')
    created_at = models.DateTimeField(auto_now_add=True)
    issued_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='issued_assignments', null=True, blank=True)
    issued_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='revoked_assignments', null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revocation_reason = models.TextField(blank=True)
    class Meta:
        ordering = ['created_at', 'id']
        constraints = [models.CheckConstraint(condition=(
            models.Q(status='DRAFT', issued_at__isnull=True, revoked_at__isnull=True) |
            models.Q(status='ISSUED', issued_at__isnull=False, revoked_at__isnull=True) |
            (models.Q(status='REVOKED', issued_at__isnull=False, revoked_at__isnull=False) & ~models.Q(revocation_reason=''))
        ), name='assignment_audit_state')]


class AssignmentEntry(models.Model):
    assignment = models.ForeignKey(Assignment, on_delete=models.CASCADE, related_name='entries')
    target_stable_id = models.UUIDField()
    scope_locked = models.BooleanField('تثبيت النطاق', default=False)
    completion_required = models.BooleanField('اشتراط الإنجاز', default=False)
    class Meta:
        ordering = ['target_stable_id']
        constraints = [models.UniqueConstraint(fields=['assignment', 'target_stable_id'], name='unique_assignment_target'),
            models.CheckConstraint(condition=models.Q(scope_locked=True) | models.Q(completion_required=True), name='entry_has_obligation')]


class Obligation(models.Model):
    entry = models.ForeignKey(AssignmentEntry, on_delete=models.CASCADE, related_name='obligations')
    node = models.ForeignKey(VisitNode, on_delete=models.CASCADE, related_name='obligations')
    scope_locked = models.BooleanField(default=False)
    completion_required = models.BooleanField(default=False)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['entry', 'node'], name='unique_entry_node_obligation')]
