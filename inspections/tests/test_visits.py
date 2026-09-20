import json
from datetime import date
from django.core.exceptions import PermissionDenied, ValidationError
from inspections.models import Visit, VisitNode
from inspections.services import visits, references as refs
from inspections.services.exports import export_visit
from .base import DomainCase


class VisitTests(DomainCase):
    def test_starts_empty_then_deep_item_has_context(self):
        visit = self.visit()
        self.assertEqual(visits.progress(visit)['total'], 0)
        self.assertEqual(visits.scope_rows(visit), [])
        visits.select_scope(self.inspector, visit.pk, self.item.pk)
        rows = visits.scope_rows(visit)
        self.assertEqual([r['context'] for r in rows], [True, True, False])
        self.assertEqual(visits.progress(visit), {'done': 0, 'total': 1, 'percent': 0})

    def test_select_branch_expands_only_that_subtree(self):
        visit = self.visit()
        visits.select_scope(self.inspector, visit.pk, self.spec.pk)
        self.assertEqual(visit.nodes.filter(selected=True).count(), 2)
        self.assertEqual(visits.progress(visit)['total'], 2)

    def test_exclusion_restore_preserves_data_and_origin(self):
        visit = self.visit()
        visits.select_scope(self.inspector, visit.pk, self.item.pk)
        node = visit.nodes.get(stable_id=self.item.pk)
        visits.record_result(self.inspector, visit.pk, node.pk, result='NONCONFORMING', observation='دليل')
        visits.exclude_scope(self.inspector, visit.pk, self.item.pk)
        self.assertEqual(visits.progress(visit)['total'], 0)
        visits.restore_scope(self.inspector, visit.pk, self.item.pk)
        node.refresh_from_db()
        self.assertEqual((node.result, node.observation, node.origin), ('NONCONFORMING', 'دليل', 'MANUAL'))
        self.assertEqual(visits.progress(visit)['percent'], 100)

    def test_local_authoring_not_governance(self):
        visit = self.visit()
        branch = visits.write_local(self.inspector, visit.pk, kind='BRANCH', title='محلي')
        spec = visits.write_local(self.inspector, visit.pk, kind='SPEC', title='وصف', parent_id=branch.stable_id)
        item = visits.write_local(self.inspector, visit.pk, kind='ITEM', title='بند', parent_id=spec.stable_id)
        visits.write_local(self.inspector, visit.pk, kind='ITEM', title='محرر', parent_id=spec.stable_id, node_id=item.pk)
        self.assertTrue(item.local)
        self.assertEqual(item.origin, 'LOCAL')
        from inspections.models import Submission
        self.assertFalse(Submission.objects.exists())

    def test_no_reference_visit_and_inactive_institution(self):
        visit = visits.create_visit(self.inspector, self.institution.pk, date.today())
        self.assertEqual(visit.reference_snapshot, {})
        self.institution.active = False
        self.institution.save()
        from django.http import Http404
        with self.assertRaises(Http404):
            self.visit()

    def test_owner_only_write_and_delete_even_admin(self):
        visit = self.visit()
        for actor in [self.other, self.admin]:
            with self.assertRaises(PermissionDenied):
                visits.select_scope(actor, visit.pk, self.item.pk)
            with self.assertRaises(PermissionDenied):
                visits.delete_draft(actor, visit.pk)
        visits.delete_draft(self.inspector, visit.pk)
        self.assertFalse(Visit.objects.filter(pk=visit.pk).exists())

    def test_invalid_result_and_context_write_rejected(self):
        visit = self.visit()
        visits.select_scope(self.inspector, visit.pk, self.item.pk)
        item = visit.nodes.get(stable_id=self.item.pk)
        with self.assertRaises(ValidationError):
            visits.record_result(self.inspector, visit.pk, item.pk, result='INVALID')
        from django.http import Http404
        with self.assertRaises(Http404):
            visits.record_result(self.inspector, visit.pk, visit.nodes.get(stable_id=self.spec.pk).pk, value='نص')

    def test_completed_blocks_all_mutations_and_deletion(self):
        visit = self.visit()
        visits.select_scope(self.inspector, visit.pk, self.item.pk)
        item = visit.nodes.get(stable_id=self.item.pk)
        completed = visits.complete_visit(self.inspector, visit.pk)
        self.assertEqual(completed.status, 'COMPLETED')
        operations = [
            lambda: visits.select_scope(self.inspector, visit.pk, self.second.pk),
            lambda: visits.exclude_scope(self.inspector, visit.pk, self.item.pk),
            lambda: visits.restore_scope(self.inspector, visit.pk, self.item.pk),
            lambda: visits.record_result(self.inspector, visit.pk, item.pk, result='CONFORMING'),
            lambda: visits.write_local(self.inspector, visit.pk, kind='ITEM', title='متأخر'),
            lambda: visits.complete_visit(self.inspector, visit.pk),
            lambda: visits.delete_draft(self.inspector, visit.pk),
        ]
        for operation in operations:
            with self.assertRaises(ValidationError):
                operation()

    def test_export_deterministic_and_historical_identity(self):
        visit = self.visit()
        visits.select_scope(self.inspector, visit.pk, self.item.pk)
        one = export_visit(self.inspector, visit)
        self.assertEqual(one, export_visit(self.inspector, visit))
        payload = json.loads(one)
        self.assertEqual(payload['schema_version'], 1)
        self.assertEqual(sorted(n['scope_role'] for n in payload['nodes']), ['AVAILABLE', 'CONTEXT', 'CONTEXT', 'SELECTED'])
        completed = visits.complete_visit(self.inspector, visit.pk)
        before = export_visit(self.inspector, completed)
        refs.delete_reference(self.admin, self.ref.pk)
        self.institution.name = 'اسم معدل'
        self.institution.save()
        self.inspector.first_name = 'اسم جديد'
        self.inspector.save()
        completed.refresh_from_db()
        self.assertEqual(before, export_visit(self.inspector, completed))
