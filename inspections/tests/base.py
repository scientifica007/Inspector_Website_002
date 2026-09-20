from datetime import date
from django.test import TestCase, override_settings
from inspections.models import User, Institution
from inspections.services import references as refs, visits


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class DomainCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user('admin', password='test-password', role='ADMIN')
        cls.inspector = User.objects.create_user('inspector', password='test-password', first_name='مفتش التجربة')
        cls.other = User.objects.create_user('other', password='test-password')
        cls.institution = Institution.objects.create(name='مركز تجريبي', kind='مركز تكوين')
        cls.ref = refs.create_reference(cls.admin, 'مرجع تجريبي', shared=True)
        cls.branch = refs.write_node(cls.admin, cls.ref.pk, kind='BRANCH', title='التنظيم')
        cls.spec = refs.write_node(cls.admin, cls.ref.pk, kind='SPEC', title='وصف البرنامج', parent_id=cls.branch.pk)
        cls.item = refs.write_node(cls.admin, cls.ref.pk, kind='ITEM', title='توفر البرنامج', parent_id=cls.spec.pk)
        cls.second = refs.write_node(cls.admin, cls.ref.pk, kind='ITEM', title='متابعة الحضور', parent_id=cls.branch.pk, position=1)

    def visit(self, owner=None, reference=None):
        return visits.create_visit(owner or self.inspector, self.institution.pk, date(2026, 9, 20), (reference or self.ref).pk)

    def entry(self, target=None, lock=False, required=False):
        return {'target_stable_id': (target or self.item).pk, 'scope_locked': lock, 'completion_required': required}
