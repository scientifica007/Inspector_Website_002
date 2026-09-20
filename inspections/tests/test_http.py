import json
import os
from io import StringIO
from unittest.mock import patch
from django.core.management import call_command
from django.test import Client
from django.urls import reverse
from inspections.models import Reference, Visit, User
from inspections.services import references as refs, visits, governance as gov
from .base import DomainCase


class HttpWorkflowTests(DomainCase):
    def test_all_workspaces_render_for_both_roles(self):
        visit = self.visit()
        for actor in [self.inspector, self.admin]:
            self.client.force_login(actor)
            for name in ['dashboard', 'institutions', 'references', 'guides', 'submissions', 'assignments', 'reference_create', 'visit_create']:
                with self.subTest(actor=actor.username, page=name):
                    self.assertEqual(self.client.get(reverse(name)).status_code, 200)
            self.assertContains(self.client.get(reverse('reference_detail', args=[self.ref.pk])), 'مرجع تجريبي')
            for tab in ['execute', 'scope', 'guides', 'assignments']:
                self.assertEqual(self.client.get(reverse('visit_detail', args=[visit.pk]), {'tab': tab}).status_code, 200)

    def test_nonadmin_direct_admin_urls_and_posts_denied(self):
        visit = self.visit()
        self.client.force_login(self.inspector)
        for name, args in [('institution_create', []), ('institution_edit', [self.institution.pk]),
                           ('guide_choose', []), ('guide_create', [self.ref.pk]), ('assignment_choose', []),
                           ('assignment_create', [visit.pk])]:
            url = reverse(name, args=args)
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)
                self.assertEqual(self.client.post(url, {}).status_code, 403)

    def test_private_reference_list_detail_and_edit_permissions(self):
        private = refs.create_reference(self.inspector, 'عنوان خاص سري')
        for actor in [self.admin, self.other]:
            self.client.force_login(actor)
            self.assertNotContains(self.client.get(reverse('references')), private.title)
            self.assertEqual(self.client.get(reverse('reference_detail', args=[private.pk])).status_code, 403)
            self.assertEqual(self.client.post(reverse('reference_edit', args=[private.pk]), {'title': 'اختراق'}).status_code, 403)

    def test_http_visit_creation_uses_day_month_year_and_empty_scope(self):
        self.client.force_login(self.inspector)
        url = reverse('visit_create')
        invalid = self.client.post(url, {'institution': self.institution.pk, 'date': '09/20/2026', 'reference': self.ref.pk})
        self.assertEqual(invalid.status_code, 200)
        self.assertFalse(Visit.objects.exists())
        valid = self.client.post(url, {'institution': self.institution.pk, 'date': '20/09/2026', 'reference': self.ref.pk})
        self.assertEqual(valid.status_code, 302)
        visit = Visit.objects.get()
        self.assertEqual(visit.date.day, 20)
        self.assertFalse(visit.nodes.filter(selected=True).exists())

    def test_cross_owner_access_mutations_and_export(self):
        visit = self.visit()
        for actor in [self.other, self.admin]:
            self.client.force_login(actor)
            self.assertEqual(self.client.post(reverse('visit_action', args=[visit.pk, 'select']), {'target': self.item.pk}).status_code, 403)
            self.assertEqual(self.client.post(reverse('visit_finalize', args=[visit.pk, 'delete'])).status_code, 403)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse('visit_detail', args=[visit.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse('visit_export', args=[visit.pk])).status_code, 403)

    def test_real_form_result_roundtrip_csrf_and_completed_conflict(self):
        visit = self.visit()
        visits.select_scope(self.inspector, visit.pk, self.item.pk)
        node = visit.nodes.get(stable_id=self.item.pk)
        self.client.force_login(self.inspector)
        url = reverse('visit_action', args=[visit.pk, 'save'])
        self.assertEqual(self.client.get(url).status_code, 405)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.inspector)
        self.assertEqual(csrf_client.post(url, {'target': node.pk, 'result': 'CONFORMING'}).status_code, 403)
        self.assertEqual(self.client.post(url, {'target': node.pk, 'result': 'NONCONFORMING', 'observation': 'دليل محفوظ'}).status_code, 302)
        self.assertContains(self.client.get(reverse('visit_detail', args=[visit.pk])), 'دليل محفوظ')
        visit = visits.complete_visit(self.inspector, visit.pk)
        before = self.client.get(reverse('visit_export', args=[visit.pk])).content
        self.assertEqual(self.client.post(url, {'target': node.pk, 'result': 'CONFORMING'}).status_code, 409)
        self.assertEqual(before, self.client.get(reverse('visit_export', args=[visit.pk])).content)

    def test_draft_assignment_not_disclosed_through_direct_url(self):
        visit = self.visit()
        assignment = gov.write_assignment(self.admin, visit.pk, 'تكليف سري', [self.entry(lock=True)])
        self.client.force_login(self.inspector)
        self.assertEqual(self.client.get(reverse('assignment_detail', args=[assignment.pk])).status_code, 403)
        self.assertNotContains(self.client.get(reverse('assignments')), 'تكليف سري')
        self.assertNotContains(self.client.get(reverse('visit_detail', args=[visit.pk]), {'tab': 'assignments'}), 'تكليف سري')

    def test_admin_assignment_form_issue_and_revoke(self):
        visit = self.visit()
        self.client.force_login(self.admin)
        response = self.client.post(reverse('assignment_create', args=[visit.pk]), {'title': 'تكليف واجهة', 'lock_' + str(self.item.pk): 'on'})
        self.assertEqual(response.status_code, 302)
        assignment = visit.assignments.get()
        self.assertEqual(self.client.get(reverse('assignment_detail', args=[assignment.pk])).status_code, 200)
        self.client.post(reverse('assignment_issue', args=[assignment.pk]))
        self.assertContains(self.client.get(reverse('assignment_detail', args=[assignment.pk])), 'صادر')
        self.client.post(reverse('assignment_revoke', args=[assignment.pk]), {'reason': 'تعليل محفوظ'})
        self.assertContains(self.client.get(reverse('assignment_detail', args=[assignment.pk])), 'تعليل محفوظ')

    def test_reference_and_guide_edit_forms(self):
        self.client.force_login(self.admin)
        for name, args in [('reference_edit', [self.ref.pk]), ('reference_node_create', [self.ref.pk]),
                           ('reference_node_edit', [self.ref.pk, self.item.pk]), ('guide_create', [self.ref.pk])]:
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 200)
        response = self.client.post(reverse('guide_create', args=[self.ref.pk]), {'title': 'دليل واجهة', 'description': '', 'targets': [str(self.item.pk)]})
        self.assertEqual(response.status_code, 302)

    def test_confirm_get_is_read_only_and_submission_review(self):
        self.client.force_login(self.inspector)
        private = refs.create_reference(self.inspector, 'مرجع اقتراح')
        refs.write_node(self.inspector, private.pk, kind='ITEM', title='بند')
        self.assertEqual(self.client.get(reverse('reference_action', args=[private.pk, 'delete'])).status_code, 200)
        self.assertTrue(Reference.objects.filter(pk=private.pk).exists())
        submission = refs.submit_reference(self.inspector, private.pk)
        self.assertEqual(self.client.get(reverse('submission_detail', args=[submission.pk])).status_code, 200)
        self.assertEqual(self.client.post(reverse('submission_detail', args=[submission.pk]), {'decision': 'approve'}).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(reverse('submission_detail', args=[submission.pk]), {'decision': 'approve', 'note': 'مقبول'}).status_code, 302)

    def test_html_escapes_authored_content(self):
        private = refs.create_reference(self.inspector, '<script>alert(1)</script>')
        self.client.force_login(self.inspector)
        response = self.client.get(reverse('reference_detail', args=[private.pk]))
        self.assertNotContains(response, '<script>alert(1)</script>')
        self.assertContains(response, '&lt;script&gt;')


class DemoTests(DomainCase):
    def test_seed_repeat_does_not_overwrite_user_edits_passwords_or_visits(self):
        env = {'DEMO_ADMIN_PASSWORD': 'fictional-admin-password', 'DEMO_INSPECTOR_PASSWORD': 'fictional-inspector-password'}
        with patch.dict(os.environ, env):
            call_command('seed_demo', stdout=StringIO())
        from inspections.management.commands.seed_demo import uid
        ref = Reference.objects.get(pk=uid('pedagogy'))
        ref.title = 'تعديل بشري محفوظ'
        ref.save()
        user = User.objects.get(username='demo_inspector')
        user.set_password('changed-password')
        user.save()
        before = Visit.objects.count()
        call_command('seed_demo', stdout=StringIO())
        ref.refresh_from_db()
        user.refresh_from_db()
        self.assertEqual(ref.title, 'تعديل بشري محفوظ')
        self.assertTrue(user.check_password('changed-password'))
        self.assertEqual(Visit.objects.count(), before)
