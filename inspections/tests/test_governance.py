import json
import uuid
from django.core.exceptions import PermissionDenied, ValidationError
from inspections.models import GuideApplication, Assignment, AssignmentEntry, Obligation
from inspections.services import visits, references as refs, governance as gov
from inspections.services.exports import export_visit
from .base import DomainCase


class GuideTests(DomainCase):
    def guide(self, targets=None):
        return gov.write_guide(self.admin, self.ref.pk, 'دليل اختياري', '', targets or [self.item.pk])

    def test_apply_preserves_manual_origin_and_never_obligates(self):
        visit = self.visit()
        visits.select_scope(self.inspector, visit.pk, self.item.pk)
        guide = self.guide([self.item.pk, self.second.pk])
        application, created = gov.apply_guide(self.inspector, visit.pk, guide.pk)
        self.assertTrue(created)
        self.assertEqual(visit.nodes.get(stable_id=self.item.pk).origin, 'MANUAL')
        self.assertEqual(visit.nodes.get(stable_id=self.second.pk).origin, 'GUIDE')
        self.assertTrue(all(not c['scope_locked'] and not c['completion_required'] for c in visits.constraints(visit).values()))

    def test_idempotence_does_not_restore_user_exclusion(self):
        visit = self.visit()
        guide = self.guide()
        gov.apply_guide(self.inspector, visit.pk, guide.pk)
        visits.exclude_scope(self.inspector, visit.pk, self.item.pk)
        _, created = gov.apply_guide(self.inspector, visit.pk, guide.pk)
        self.assertFalse(created)
        self.assertEqual(GuideApplication.objects.count(), 1)
        self.assertEqual(visit.nodes.get(stable_id=self.item.pk).state, 'EXCLUDED')

    def test_temporal_mismatch_skips_missing_target_without_live_import(self):
        visit = self.visit()
        later = refs.write_node(self.admin, self.ref.pk, kind='ITEM', title='لاحق')
        guide = self.guide([self.item.pk, later.pk])
        application, _ = gov.apply_guide(self.inspector, visit.pk, guide.pk)
        self.assertEqual(application.skipped, [str(later.pk)])
        self.assertFalse(visit.nodes.filter(stable_id=later.pk).exists())
        self.assertEqual(visits.progress(visit)['total'], 1)

    def test_changed_deleted_guide_does_not_change_prior_application(self):
        visit = self.visit()
        guide = self.guide()
        gov.apply_guide(self.inspector, visit.pk, guide.pk)
        before = export_visit(self.inspector, visit)
        gov.write_guide(self.admin, self.ref.pk, 'تغيير', '', [self.second.pk], guide.pk)
        gov.delete_guide(self.admin, guide.pk)
        self.assertEqual(before, export_visit(self.inspector, visit))

    def test_mixed_targets_and_overlapping_subtrees_no_duplicate_nodes(self):
        visit = self.visit()
        guide = self.guide([self.branch.pk, self.spec.pk, self.item.pk])
        gov.apply_guide(self.inspector, visit.pk, guide.pk)
        self.assertEqual(visit.nodes.filter(selected=True).count(), 4)

    def test_permissions_and_incompatible_reference(self):
        with self.assertRaises(PermissionDenied):
            gov.write_guide(self.inspector, self.ref.pk, 'غير مسموح', '', [self.item.pk])
        visit = self.visit()
        guide = self.guide()
        with self.assertRaises(PermissionDenied):
            gov.apply_guide(self.other, visit.pk, guide.pk)
        other = refs.create_reference(self.admin, 'مختلف', shared=True)
        wrong_visit = self.visit(reference=other)
        with self.assertRaises(ValidationError):
            gov.apply_guide(self.inspector, wrong_visit.pk, guide.pk)


class AssignmentTests(DomainCase):
    def assignment(self, visit, entries=None, issue=True):
        a = gov.write_assignment(self.admin, visit.pk, 'تكليف رسمي', entries or [self.entry(lock=True)])
        if issue:
            gov.issue_assignment(self.admin, a.pk)
        a.refresh_from_db()
        return a

    def test_draft_hidden_in_list_and_export_until_issued(self):
        visit = self.visit()
        a = self.assignment(visit, issue=False)
        self.assertFalse(gov.visible_assignments(self.inspector, visit).exists())
        self.assertEqual(json.loads(export_visit(self.inspector, visit))['assignments'], [])
        self.assertEqual(visits.progress(visit)['total'], 0)
        gov.issue_assignment(self.admin, a.pk)
        self.assertTrue(gov.visible_assignments(self.inspector, visit).exists())

    def test_issue_atomic_invalid_target_has_no_partial_effect(self):
        visit = self.visit()
        a = self.assignment(visit, issue=False)
        AssignmentEntry.objects.create(assignment=a, target_stable_id=uuid.uuid4(), completion_required=True)
        with self.assertRaises(ValidationError):
            gov.issue_assignment(self.admin, a.pk)
        a.refresh_from_db()
        self.assertEqual(a.status, 'DRAFT')
        self.assertFalse(visit.nodes.filter(selected=True).exists())
        self.assertFalse(Obligation.objects.exists())

    def test_branch_lock_blocks_ancestor_and_descendant_exclusion(self):
        visit = self.visit()
        self.assignment(visit, [self.entry(self.branch, lock=True)])
        for target in [self.branch, self.spec, self.item, self.second]:
            with self.assertRaises(ValidationError):
                visits.exclude_scope(self.inspector, visit.pk, target.pk)

    def test_deep_lock_cannot_be_bypassed_by_excluding_context_ancestor(self):
        visit = self.visit()
        self.assignment(visit)
        with self.assertRaises(ValidationError):
            visits.exclude_scope(self.inspector, visit.pk, self.branch.pk)

    def test_overlapping_obligations_revoke_only_own_constraint(self):
        visit = self.visit()
        visits.select_scope(self.inspector, visit.pk, self.item.pk)
        lock = self.assignment(visit, [self.entry(lock=True)])
        required = self.assignment(visit, [self.entry(required=True)])
        node = visit.nodes.get(stable_id=self.item.pk)
        self.assertEqual(node.origin, 'MANUAL')
        gov.revoke_assignment(self.admin, lock.pk, 'تعديل التكليف')
        constraints = visits.constraints(visit)[node.pk]
        self.assertFalse(constraints['scope_locked'])
        self.assertTrue(constraints['completion_required'])
        self.assertEqual(constraints['assignments'], [str(required.pk)])

    def test_baseline_constraint_survives_revocation(self):
        visit = self.visit()
        visits.select_scope(self.inspector, visit.pk, self.item.pk)
        node = visit.nodes.get(stable_id=self.item.pk)
        node.baseline_scope_locked = True
        node.baseline_completion_required = True
        node.save()
        a = self.assignment(visit)
        gov.revoke_assignment(self.admin, a.pk, 'سبب')
        self.assertTrue(visits.constraints(visit)[node.pk]['scope_locked'])
        self.assertTrue(visits.constraints(visit)[node.pk]['completion_required'])

    def test_completion_required_independent_from_lock_and_cannot_be_evaded(self):
        visit = self.visit()
        self.assignment(visit, [self.entry(required=True)])
        visits.exclude_scope(self.inspector, visit.pk, self.item.pk)
        with self.assertRaises(ValidationError):
            visits.complete_visit(self.inspector, visit.pk)
        visits.restore_scope(self.inspector, visit.pk, self.item.pk)
        with self.assertRaises(ValidationError):
            visits.complete_visit(self.inspector, visit.pk)
        node = visit.nodes.get(stable_id=self.item.pk)
        visits.record_result(self.inspector, visit.pk, node.pk, result='NOT_APPLICABLE', observation='لا ينطبق على الحالة')
        self.assertEqual(visits.complete_visit(self.inspector, visit.pk).status, 'COMPLETED')

    def test_branch_requires_specifications_and_items_not_structural_node(self):
        visit = self.visit()
        self.assignment(visit, [self.entry(self.branch, required=True)])
        self.assertFalse(visits.constraints(visit)[visit.nodes.get(stable_id=self.branch.pk).pk]['completion_required'])
        for n in visit.nodes.filter(selected=True).exclude(kind='BRANCH'):
            visits.record_result(self.inspector, visit.pk, n.pk, result='CONFORMING' if n.kind == 'ITEM' else '', value='وصف')
        visits.complete_visit(self.inspector, visit.pk)

    def test_empty_branch_adds_no_fake_completion_requirement(self):
        empty = refs.write_node(self.admin, self.ref.pk, kind='BRANCH', title='فارغ')
        visit = self.visit()
        self.assignment(visit, [self.entry(empty, required=True)])
        self.assertEqual(visits.progress(visit)['total'], 0)
        visits.complete_visit(self.inspector, visit.pk)

    def test_revocation_requires_reason_and_preserves_data(self):
        visit = self.visit()
        a = self.assignment(visit)
        node = visit.nodes.get(stable_id=self.item.pk)
        visits.record_result(self.inspector, visit.pk, node.pk, result='CONFORMING', observation='محفوظ')
        with self.assertRaises(ValidationError):
            gov.revoke_assignment(self.admin, a.pk, '   ')
        gov.revoke_assignment(self.admin, a.pk, 'انتهاء الحاجة')
        node.refresh_from_db()
        self.assertEqual((node.state, node.result, node.observation), ('ACTIVE', 'CONFORMING', 'محفوظ'))
        audit = json.loads(export_visit(self.inspector, visit))['assignments'][0]
        self.assertEqual(audit['status'], 'REVOKED')
        self.assertEqual(audit['revocation_reason'], 'انتهاء الحاجة')
        self.assertEqual(audit['revoked_by_id'], self.admin.pk)

    def test_completed_no_issue_revoke_edit_or_apply_guide(self):
        visit = self.visit()
        issued = self.assignment(visit)
        draft = self.assignment(visit, issue=False)
        guide = gov.write_guide(self.admin, self.ref.pk, 'دليل', '', [self.item.pk])
        visit = visits.complete_visit(self.inspector, visit.pk)
        before = export_visit(self.inspector, visit)
        for fn in [lambda: gov.issue_assignment(self.admin, draft.pk),
                   lambda: gov.revoke_assignment(self.admin, issued.pk, 'سبب'),
                   lambda: gov.apply_guide(self.inspector, visit.pk, guide.pk),
                   lambda: gov.write_assignment(self.admin, visit.pk, 'لاحق', [self.entry(lock=True)])]:
            with self.assertRaises(ValidationError):
                fn()
        visit.refresh_from_db()
        self.assertEqual(export_visit(self.inspector, visit), before)

    def test_permissions_and_issued_content_immutable(self):
        visit = self.visit()
        a = self.assignment(visit)
        with self.assertRaises(PermissionDenied):
            gov.revoke_assignment(self.inspector, a.pk, 'سبب')
        with self.assertRaises(PermissionDenied):
            gov.issue_assignment(self.inspector, a.pk)
        with self.assertRaises(PermissionDenied):
            gov.write_assignment(self.inspector, visit.pk, 'غير مسموح', [self.entry(lock=True)])
        with self.assertRaises(ValidationError):
            gov.write_assignment(self.admin, visit.pk, 'تغيير صادر', [self.entry(required=True)], a.pk)
        with self.assertRaises(ValidationError):
            gov.issue_assignment(self.admin, a.pk)

    def test_draft_delete_includes_assignment_cascade(self):
        visit = self.visit()
        self.assignment(visit)
        visits.delete_draft(self.inspector, visit.pk)
        self.assertFalse(Assignment.objects.exists())
