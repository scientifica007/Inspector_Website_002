"""Opt-in, repeat-safe fictional records. Existing records are never overwritten."""
import os
import uuid
from datetime import date
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from inspections.models import User, Institution, Reference, ReferenceNode, Guide, Visit
from inspections.services import visits, governance

NAMESPACE = uuid.UUID('180a1e8e-21ba-4225-b460-a45037a18893')


def uid(name):
    return uuid.uuid5(NAMESPACE, name)


class Command(BaseCommand):
    help = 'Create optional fictional demo data. Set DEMO_ADMIN_PASSWORD and DEMO_INSPECTOR_PASSWORD for first run.'

    @transaction.atomic
    def handle(self, *args, **options):
        users = {}
        for username, role, name, env in [
            ('demo_admin', 'ADMIN', 'إدارة التجربة', 'DEMO_ADMIN_PASSWORD'),
            ('demo_inspector', 'INSPECTOR', 'مفتش التجربة', 'DEMO_INSPECTOR_PASSWORD'),
        ]:
            user = User.objects.filter(username=username).first()
            if not user:
                password = os.getenv(env, '')
                if len(password) < 12:
                    raise CommandError(f'Set {env} to a password of at least 12 characters. No default password is provided.')
                user = User.objects.create_user(username, password=password, role=role, first_name=name)
            elif user.role != role:
                raise CommandError(f'{username} already exists with another role; nothing overwritten.')
            users[role] = user
        institutions = []
        for name, kind in [
            ('مركز التكوين المهني — مؤسسة تجريبية أ', 'مركز تكوين مهني وتمهين'),
            ('المعهد الوطني المتخصص — مؤسسة تجريبية ب', 'معهد وطني متخصص'),
            ('معهد التعليم المهني — مؤسسة تجريبية ج', 'معهد تعليم مهني'),
        ]:
            institution, _ = Institution.objects.get_or_create(name=name, defaults={'kind': kind})
            institutions.append(institution)
        reference, fresh = Reference.objects.get_or_create(pk=uid('pedagogy'), defaults={
            'title': 'مرجع التفتيش البيداغوجي — تجريبي', 'description': 'متابعة تنظيم التكوين وتنفيذ البرامج والتقييم. محتوى توضيحي قابل للتعديل؛ ليس مرجعًا تنظيميًا معتمدًا.',
            'owner': users['ADMIN'], 'visibility': 'SHARED', 'provenance': {'demo': True}})
        structure = [
            ('organisation', None, 'BRANCH', 'تنظيم العملية التكوينية', ''),
            ('programme', 'organisation', 'SPEC', 'البرنامج والتوزيع الزمني', 'سجل التخصص والمستوى والفترة التي تشملها الزيارة.'),
            ('programme_available', 'programme', 'ITEM', 'توفر البرنامج المرجعي للتخصص', ''),
            ('progression', 'programme', 'ITEM', 'توافق التدرج مع البرنامج المقرر', ''),
            ('attendance', 'organisation', 'ITEM', 'انتظام توثيق حضور المتكونين', ''),
            ('delivery', None, 'BRANCH', 'تنفيذ الحصة التكوينية', ''),
            ('objectives', 'delivery', 'ITEM', 'وضوح أهداف الحصة للمتكونين', ''),
            ('methods', 'delivery', 'ITEM', 'ملاءمة طرائق التكوين للكفاءات المستهدفة', ''),
            ('resources', 'delivery', 'ITEM', 'توظيف الوسائل البيداغوجية الملائمة', ''),
            ('assessment', None, 'BRANCH', 'التقييم والمتابعة', ''),
            ('evaluation', 'assessment', 'ITEM', 'ارتباط معايير التقييم بالكفاءات', ''),
            ('feedback', 'assessment', 'ITEM', 'تقديم تغذية راجعة قابلة للاستثمار', ''),
        ]
        if fresh:
            for position, (key, parent, kind, title, description) in enumerate(structure):
                ReferenceNode.objects.create(id=uid(key), reference=reference, parent_id=uid(parent) if parent else None,
                    kind=kind, title=title, description=description, position=position)
            Guide.objects.create(id=uid('guide-initial'), reference=reference, title='متابعة أولية لتنظيم التكوين',
                description='اقتراح يجمع البرنامج والتدرج والحضور، ويمكن تعديل النطاق بعد تطبيقه.',
                targets=[str(uid('programme')), str(uid('attendance'))])
            # Visits are created only with the newly created demo reference, never on reruns.
            draft = visits.create_visit(users['INSPECTOR'], institutions[0].pk, date(2026, 9, 20), reference.pk)
            visits.select_scope(users['INSPECTOR'], draft.pk, uid('organisation'))
            item = draft.nodes.get(stable_id=uid('programme_available'))
            visits.record_result(users['INSPECTOR'], draft.pk, item.pk, result='CONFORMING', observation='عُرض البرنامج أثناء التجربة.')
            spec = draft.nodes.get(stable_id=uid('programme'))
            visits.record_result(users['INSPECTOR'], draft.pk, spec.pk, value='تخصص تجريبي — مستوى تأهيلي — الفترة الأولى')
            assignment = governance.write_assignment(users['ADMIN'], draft.pk, 'التحقق من توثيق الحضور — تجريبي',
                [{'target_stable_id': uid('attendance'), 'scope_locked': True, 'completion_required': True}])
            governance.issue_assignment(users['ADMIN'], assignment.pk)
            complete = visits.create_visit(users['INSPECTOR'], institutions[1].pk, date(2026, 9, 16), reference.pk)
            visits.select_scope(users['INSPECTOR'], complete.pk, uid('assessment'))
            for node in complete.nodes.filter(selected=True, kind='ITEM'):
                visits.record_result(users['INSPECTOR'], complete.pk, node.pk, result='CONFORMING')
            visits.complete_visit(users['INSPECTOR'], complete.pk)
            visits.create_visit(users['INSPECTOR'], institutions[2].pk, date(2026, 9, 23), reference.pk)
        self.stdout.write(self.style.SUCCESS('Demo data available. Existing content and passwords were preserved.'))
