from django.core.exceptions import PermissionDenied, ValidationError
from inspections.models import Reference, Submission
from inspections.services import references as refs, visits
from inspections.services.common import require_reference
from .base import DomainCase


class ReferenceTests(DomainCase):
    def test_inspector_cannot_create_shared_or_edit_shared(self):
        with self.assertRaises(PermissionDenied):
            refs.create_reference(self.inspector, 'غير مسموح', shared=True)
        with self.assertRaises(PermissionDenied):
            refs.update_reference(self.inspector, self.ref.pk, 'معدل', '')

    def test_private_visibility_includes_only_owner(self):
        private = refs.create_reference(self.inspector, 'خاص')
        require_reference(self.inspector, private)
        for user in [self.other, self.admin]:
            with self.assertRaises(PermissionDenied):
                require_reference(user, private)
            with self.assertRaises(PermissionDenied):
                self.visit(owner=user, reference=private)

    def test_reference_edit_reorder_delete_does_not_touch_snapshot(self):
        visit = self.visit()
        frozen = visit.reference_snapshot
        refs.write_node(self.admin, self.ref.pk, kind='ITEM', title='عنوان أحدث', parent_id=self.branch.pk, position=99, node_id=self.second.pk)
        refs.delete_node(self.admin, self.ref.pk, self.item.pk)
        refs.update_reference(self.admin, self.ref.pk, 'مرجع جديد', 'تعريف جديد')
        visit.refresh_from_db()
        self.assertEqual(visit.reference_snapshot, frozen)
        self.assertEqual(visit.nodes.get(stable_id=self.second.pk).title, 'متابعة الحضور')

    def test_reference_deletion_preserves_visit_and_future_execution(self):
        visit = self.visit()
        refs.delete_reference(self.admin, self.ref.pk)
        visit.refresh_from_db()
        self.assertEqual(visit.nodes.count(), 4)
        visits.select_scope(self.inspector, visit.pk, self.item.pk)
        self.assertEqual(visits.progress(visit)['total'], 1)

    def test_invalid_parent_and_cycles_rejected(self):
        with self.assertRaises(ValidationError):
            refs.write_node(self.admin, self.ref.pk, kind='BRANCH', title='فرع', parent_id=self.item.pk)
        with self.assertRaises(ValidationError):
            refs.write_node(self.admin, self.ref.pk, kind='BRANCH', title='دورة', parent_id=self.branch.pk, node_id=self.branch.pk)

    def test_cross_reference_parent_rejected(self):
        other_ref = refs.create_reference(self.admin, 'ثان', shared=True)
        from django.http import Http404
        with self.assertRaises(Http404):
            refs.write_node(self.admin, other_ref.pk, kind='ITEM', title='غريب', parent_id=self.branch.pk)


class SubmissionTests(DomainCase):
    def private_submission(self):
        private = refs.create_reference(self.inspector, 'مرجعي')
        refs.write_node(self.inspector, private.pk, kind='ITEM', title='النسخة المرسلة')
        return private, refs.submit_reference(self.inspector, private.pk)

    def test_snapshot_survives_edit_and_source_delete_and_approval(self):
        private, submission = self.private_submission()
        refs.update_reference(self.inspector, private.pk, 'تحرير لاحق', '')
        refs.delete_reference(self.inspector, private.pk)
        refs.review_submission(self.admin, submission.pk, True, 'مقبول')
        submission.refresh_from_db()
        shared = Reference.objects.get(pk=submission.published_reference_id)
        self.assertEqual(shared.title, 'مرجعي')
        self.assertEqual(shared.nodes.get().title, 'النسخة المرسلة')
        self.assertNotEqual(str(shared.nodes.get().pk), submission.snapshot['nodes'][0]['id'])

    def test_rejection_keeps_private_ownership(self):
        private, submission = self.private_submission()
        refs.review_submission(self.admin, submission.pk, False, 'يحتاج تطويرًا')
        private.refresh_from_db()
        self.assertEqual(private.visibility, 'PRIVATE')
        self.assertEqual(private.owner, self.inspector)

    def test_approval_is_independent_and_cannot_repeat(self):
        private, submission = self.private_submission()
        refs.review_submission(self.admin, submission.pk, True)
        private.refresh_from_db()
        self.assertEqual(private.visibility, 'PRIVATE')
        with self.assertRaises(ValidationError):
            refs.review_submission(self.admin, submission.pk, True)

    def test_duplicate_submission_and_nonadmin_review_rejected(self):
        private, submission = self.private_submission()
        with self.assertRaises(ValidationError):
            refs.submit_reference(self.inspector, private.pk)
        with self.assertRaises(PermissionDenied):
            refs.review_submission(self.inspector, submission.pk, True)
