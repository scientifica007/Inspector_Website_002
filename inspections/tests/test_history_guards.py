from django.db import IntegrityError, transaction
from inspections.models import Visit, VisitNode, AssignmentEntry, GuideApplication, Obligation
from inspections.services import visits, governance as gov, references as refs
from .base import DomainCase


class HistoryGuardTests(DomainCase):
    def rejected(self, operation):
        with self.assertRaises(IntegrityError), transaction.atomic():
            operation()

    def test_completed_bulk_update_delete_insert_blocked(self):
        visit = self.visit()
        visits.select_scope(self.inspector, visit.pk, self.item.pk)
        assignment = gov.write_assignment(self.admin, visit.pk, 'تكليف', [self.entry(lock=True)])
        gov.issue_assignment(self.admin, assignment.pk)
        guide = gov.write_guide(self.admin, self.ref.pk, 'دليل', '', [self.second.pk])
        gov.apply_guide(self.inspector, visit.pk, guide.pk)
        visits.complete_visit(self.inspector, visit.pk)
        for operation in [
            lambda: Visit.objects.filter(pk=visit.pk).update(status='DRAFT', completed_at=None, completed_payload=None),
            lambda: Visit.objects.filter(pk=visit.pk).delete(),
            lambda: visit.nodes.update(observation='تغيير خفي'),
            lambda: visit.nodes.all().delete(),
            lambda: VisitNode.objects.create(visit=visit, kind='ITEM', title='متأخر'),
            lambda: visit.assignments.update(title='تغيير خفي'),
            lambda: AssignmentEntry.objects.filter(assignment=assignment).update(scope_locked=False),
            lambda: Obligation.objects.all().delete(),
            lambda: GuideApplication.objects.filter(visit=visit).update(snapshot={}),
        ]:
            self.rejected(operation)

    def test_frozen_material_and_origin_cannot_be_rewritten_in_draft(self):
        visit = self.visit()
        self.rejected(lambda: Visit.objects.filter(pk=visit.pk).update(reference_snapshot={}))
        self.rejected(lambda: visit.nodes.update(title='استبدال'))
        visits.select_scope(self.inspector, visit.pk, self.item.pk)
        self.rejected(lambda: visit.nodes.filter(stable_id=self.item.pk).update(origin='GUIDE'))

    def test_submission_snapshot_guard(self):
        private = refs.create_reference(self.inspector, 'خاص')
        refs.write_node(self.inspector, private.pk, kind='ITEM', title='بند')
        submission = refs.submit_reference(self.inspector, private.pk)
        from inspections.models import Submission
        self.rejected(lambda: Submission.objects.filter(pk=submission.pk).update(snapshot={}))
