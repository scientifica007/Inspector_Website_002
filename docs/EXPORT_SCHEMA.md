# JSON export — inspector-visit / 1

نوع المحتوى `application/json; charset=utf-8`. اسم الملف `inspection-<visit UUID>.json`.
المفاتيح مرتبة أبجديًا، UTF-8 دون escaping غير ضروري للعربية، indent=2، ونهاية سطر واحدة.
لا `exported_at` ولا timestamp متغير عند كل تنزيل. الوقت المخزن هو وقت حدث حقيقي فقط.

| الحقل | المعنى |
|---|---|
| `schema` | القيمة الثابتة `inspector-visit` |
| `schema_version` | العدد `1`؛ تغيير غير متوافق يحتاج إصدارًا جديدًا |
| `visit` | UUID، date بصيغة ISO، status، created_at، completed_at |
| `institution` | id/name/kind كما جُمّدت عند الإنشاء |
| `inspector` | id/username/name كما جُمّدت عند الإنشاء |
| `reference_snapshot` | مادة المرجع الأصلية أو `{}` لزيارة بلا مرجع |
| `progress` | done/total/percent للعناصر النشطة القابلة للإنجاز |
| `nodes` | كل العقد المجمدة والمحلية مع أدوار النطاق وبيانات التنفيذ |
| `guide_applications` | المادة المطبقة وبصمتها ووقت التطبيق وصاحبه والإضافات والمتخطيات |
| `assignments` | سجل التكليفات ISSUED وREVOKED فقط، مع أهدافها والتوسع الفعلي للقيود |

`reference_snapshot` يحوي schema_version=1، id/title/description/visibility/owner_id/created_at/updated_at/provenance،
وnodes تحوي id/parent_id/kind/title/description/position. لا يحمل pointers إلى بيانات حية واجبة القراءة لفهم الماضي.

كل عقدة في `nodes`:

| الحقول | النوع/القيم |
|---|---|
| `id`, `stable_id`, `parent_stable_id` | UUID كنص؛ الأب قد يكون null. الأول معرف صف الزيارة، والثاني هوية العنصر عبر اللقطة والأدلة والتكليفات |
| `kind` | BRANCH / SPEC / ITEM |
| `title`, `description`, `position` | النصوص المجمدة أو المحلية والترتيب |
| `scope_role` | SELECTED / CONTEXT / AVAILABLE |
| `state` | ACTIVE / EXCLUDED؛ ACTIVE وحدها لا تعني أن العقدة مختارة |
| `origin` | LEGACY / MANUAL / GUIDE / ASSIGNMENT / LOCAL أو null قبل الاختيار |
| `local` | boolean |
| `baseline` | scope_locked وcompletion_required الأصليان |
| `effective` | scope_locked وcompletion_required الفعليان، وassignments: قائمة UUID للتكليفات السارية المساهمة |
| `result` | CONFORMING / NONCONFORMING / NOT_APPLICABLE أو null |
| `value`, `observation` | نصوص محفوظة، وقد تكون فارغة |

النتيجة `NOT_APPLICABLE` تعني «غير منطبق»، وهي مختلفة عن `NONCONFORMING` أي «غير مطابق».
السياق والمتاح والمستبعد لا يدخلون progress. يمكن أن يحمل المستبعد نتيجة وملاحظة سابقتين؛ هذا مقصود لحفظ الاسترجاع.

سجل التكليف يحتوي id/title/status، created_by_id/created_at، issued_by_id/issued_at، revoked_by_id/revoked_at،
revocation_reason، وentries. كل Entry يحوي target_stable_id وscope_locked وcompletion_required،
وexpanded_obligations تحدد node_stable_id وقيديه وقت الإصدار. الإلغاء لا يحذف هذا التوسع التاريخي.
لا تُصدّر مسودات الإدارة المخفية، حتى في تصدير الإدارة، لتوحيد معنى الملف.

ترتيب العقد ثابت حسب position ثم stable_id، وترتيب التكليفات والأدلة حسب توقيت الحدث ثم الهوية/المعرف.
عند COMPLETED تُخزن المادة كاملة؛ أي تنزيل لاحق يعيدها دون إعادة تفسير القيود من المصادر الحية.
حراس قاعدة البيانات تمنع تغيير سجلاتها المرتبطة بعد ذلك.

التصدير للتوثيق والقراءة؛ لا توجد وظيفة استيراد في هذه النسخة. لا تعدّل schema_version عند نقل الملف أو مقارنته.
