from django import forms
from django.db.models import Q
from inspections.models import Institution, Reference, NodeKind, VisitNode, Visit


class InstitutionForm(forms.ModelForm):
    class Meta:
        model = Institution
        fields = ['name', 'kind', 'active']


class ReferenceForm(forms.Form):
    title = forms.CharField(label='اسم المرجع', max_length=240)
    description = forms.CharField(label='تعريف المرجع', required=False, widget=forms.Textarea(attrs={'rows': 3}))
    shared = forms.BooleanField(label='مرجع مشترك لجميع المفتشين', required=False)

    def __init__(self, *args, actor, editing=False, **kwargs):
        super().__init__(*args, **kwargs)
        if not actor.is_admin or editing:
            self.fields.pop('shared')


class NodeForm(forms.Form):
    kind = forms.ChoiceField(label='نوع العنصر', choices=NodeKind.choices)
    title = forms.CharField(label='العنوان', max_length=300)
    description = forms.CharField(label='توضيح', required=False, widget=forms.Textarea(attrs={'rows': 3}))
    parent_id = forms.ChoiceField(label='العنصر الأب', required=False)
    position = forms.IntegerField(label='الترتيب', initial=0, min_value=0, help_text='الأصغر يظهر أولًا بين العناصر المتجاورة.')

    def __init__(self, *args, nodes, local=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['parent_id'].choices = [('', 'عنصر رئيسي')] + [(str(n.stable_id if local else n.pk), f'{n.get_kind_display()} — {n.title}') for n in nodes if n.kind != 'ITEM']


class VisitForm(forms.Form):
    institution = forms.ModelChoiceField(label='المؤسسة', queryset=Institution.objects.filter(active=True))
    date = forms.DateField(label='تاريخ الزيارة — يوم / شهر / سنة', input_formats=['%d/%m/%Y'],
        widget=forms.DateInput(format='%d/%m/%Y', attrs={'placeholder': 'dd/mm/yyyy', 'dir': 'ltr', 'inputmode': 'numeric', 'autocomplete': 'off'}))
    reference = forms.ModelChoiceField(label='المرجع', queryset=Reference.objects.none(), required=False, empty_label='زيارة بمحتوى محلي فقط')

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['reference'].queryset = Reference.objects.filter(Q(visibility='SHARED') | Q(owner=actor))


class ResultForm(forms.Form):
    result = forms.ChoiceField(label='نتيجة الفحص', choices=[('', 'لم يُفحص بعد')] + VisitNode.Result.choices, required=False)
    value = forms.CharField(label='القيمة / الوصف المسجل', required=False, widget=forms.Textarea(attrs={'rows': 2}))
    observation = forms.CharField(label='الملاحظة والأدلة', required=False, widget=forms.Textarea(attrs={'rows': 2}))


class TargetForm(forms.Form):
    target = forms.UUIDField()


class ReviewForm(forms.Form):
    decision = forms.ChoiceField(label='القرار', choices=[('approve', 'قبول وإنشاء مرجع مشترك مستقل'), ('reject', 'رفض الاقتراح')])
    note = forms.CharField(label='تعليل القرار', required=False, widget=forms.Textarea(attrs={'rows': 3}))


class ReasonForm(forms.Form):
    reason = forms.CharField(label='سبب إلغاء التكليف', widget=forms.Textarea(attrs={'rows': 3}))


class GuideForm(forms.Form):
    title = forms.CharField(label='اسم الدليل', max_length=240)
    description = forms.CharField(label='وصف الدليل', required=False, widget=forms.Textarea(attrs={'rows': 3}))
    targets = forms.MultipleChoiceField(label='العناصر المقترحة', widget=forms.CheckboxSelectMultiple)

    def __init__(self, *args, nodes, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['targets'].choices = [(str(n.pk), f'{n.get_kind_display()} — {n.title}') for n in nodes]


class SharedReferenceForm(forms.Form):
    reference = forms.ModelChoiceField(label='المرجع المشترك', queryset=Reference.objects.filter(visibility='SHARED'))


class DraftChoice(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.institution_snapshot['name']} — {obj.date.strftime('%d/%m/%Y')} — {obj.inspector_snapshot['name']}"


class AssignmentVisitForm(forms.Form):
    visit = DraftChoice(label='الزيارة المستهدفة', queryset=Visit.objects.filter(status='DRAFT', source_reference_id__isnull=False))


class AssignmentForm(forms.Form):
    title = forms.CharField(label='عنوان التكليف', max_length=240)

    def __init__(self, *args, visit, entries=None, **kwargs):
        self.targets = visit.reference_snapshot.get('nodes', [])
        entries = entries or {}
        super().__init__(*args, **kwargs)
        self.rows = []
        for node in self.targets:
            key = node['id']
            old = entries.get(key, {})
            lock, required = 'lock_' + key, 'required_' + key
            self.fields[lock] = forms.BooleanField(label='تثبيت النطاق', required=False, initial=old.get('scope_locked', False))
            self.fields[required] = forms.BooleanField(label='اشتراط الإنجاز', required=False, initial=old.get('completion_required', False))
            self.rows.append({'node': node, 'lock': self[lock], 'required': self[required]})

    def clean(self):
        data = super().clean()
        self.entries = [{'target_stable_id': n['id'], 'scope_locked': data.get('lock_' + n['id'], False), 'completion_required': data.get('required_' + n['id'], False)} for n in self.targets if data.get('lock_' + n['id']) or data.get('required_' + n['id'])]
        if not self.entries:
            raise forms.ValidationError('اختر قيدًا واحدًا على الأقل لأحد العناصر.')
        return data
