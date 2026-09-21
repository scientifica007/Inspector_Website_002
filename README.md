# Inspector_Website_002
Inspector Website 002

تطبيق Django عربي RTL لإدارة الزيارات التفتيشية والمراجع والأدلة والتكليفات الرسمية.
بناء مستقل داخل هذا المستودع. الفرع التجريبي: `build/independent-rebuild`.
**القبول البشري Pending؛ لا يُدمج الفرع إلى main دون موافقة المالك.**

## التشغيل من نسخة نظيفة

المتطلبات: Python 3.12، Git، وبيئة تدعم `venv` و`pip`. لا تحتاج Node أو Seed لتشغيل التطبيق.
اختُبرت قاعدة SQLite في التطوير وPostgreSQL 16 في CI.

```bash
git clone --branch build/independent-rebuild --single-branch https://github.com/scientifica007/Inspector_Website_002.git
cd Inspector_Website_002
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

حرر `.env` بحسب بيئتك. لا يقرأه Django تلقائيًا؛ لتحميله في Bash:

```bash
set -a
source .env
set +a
python manage.py migrate --noinput
python manage.py check
python manage.py createsuperuser
python manage.py create_inspector inspector --name 'مفتش'
python manage.py runserver
```

افتح `http://127.0.0.1:8000/`. حساب `createsuperuser` يُعطى دور الإدارة. أمر `create_inspector`
يطلب كلمة المرور تفاعليًا، ولا يغيّر حسابًا موجودًا. أضف مؤسسة ومرجعًا من حساب الإدارة، ثم ابدأ زيارة من حساب المفتش.

## بيانات التجربة الاختيارية

مؤسسات ومحتوى وهمي موسوم بأنه تجريبي، لا يتضمن بيانات شخصية ولا يمثل مرجعًا رسميًا معتمدًا.
يوفر حسابي `demo_admin` و`demo_inspector`، وثلاث مؤسسات، ومرجعًا هرميًا يضم ثمانية بنود،
ودليلًا وتكليفًا وزيارات في حالات مختلفة. اختر بنفسك كلمتي مرور بطول 12 محرفًا على الأقل:

```bash
read -r -s -p 'Demo admin password: ' DEMO_ADMIN_PASSWORD
export DEMO_ADMIN_PASSWORD
read -r -s -p 'Demo inspector password: ' DEMO_INSPECTOR_PASSWORD
export DEMO_INSPECTOR_PASSWORD
python manage.py seed_demo
unset DEMO_ADMIN_PASSWORD DEMO_INSPECTOR_PASSWORD
```

لا توجد كلمات مرور افتراضية. إعادة `seed_demo` تحافظ على المحتوى وكلمات المرور الموجودة ولا تكرر الزيارات.
لا تستعمل الحسابات التجريبية في نشر حقيقي. يمكن تغيير كلمة مرور حساب محلي عبر `python manage.py changepassword USERNAME`.

## إعدادات البيئة

| المتغير | الغرض |
|---|---|
| `DJANGO_DEBUG` | `1` للتطوير؛ `0` للإنتاج |
| `DJANGO_SECRET_KEY` | مفتاح مستقل طويل؛ إلزامي عند تعطيل DEBUG |
| `DJANGO_ALLOWED_HOSTS` | أسماء/IP الخوادم المسموح بها، مفصولة بفواصل؛ لا تستخدم `*` |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | أصول HTTPS موثوقة عند الحاجة، مفصولة بفواصل |
| `DJANGO_DB_PATH` | مسار قاعدة SQLite؛ الافتراضي `db.sqlite3` داخل المشروع |
| `POSTGRES_DB/USER/PASSWORD/HOST/PORT` | تشغيل PostgreSQL بدل SQLite عند تحديد `POSTGRES_DB` |

المنطقة الزمنية `Africa/Algiers`. عرض وإدخال تاريخ الزيارة `dd/mm/yyyy`، بينما تاريخ JSON وفق ISO 8601.
ملفات `.env` وقواعد البيانات ونتائج الاختبار غير مدرجة في Git.

## الاختبار من هاتف عبر الشبكة المحلية

صل الهاتف والحاسوب بالشبكة نفسها، واعرف عنوان IPv4 الحالي للحاسوب (`hostname -I` في Linux).
أضف العنوان الفعلي إلى `DJANGO_ALLOWED_HOSTS`؛ لا يوجد عنوان محلي مثبت في الكود:

```bash
read -r -p 'Computer LAN IPv4: ' INSPECTOR_LAN_IP
export DJANGO_ALLOWED_HOSTS="localhost,127.0.0.1,$INSPECTOR_LAN_IP"
export DJANGO_DEBUG=1
python manage.py runserver 0.0.0.0:8000
```

افتح على الهاتف `http://<عنوان-الحاسوب>:8000/`. إذا تعذر الاتصال، تحقق من الشبكة وعزل الأجهزة وقاعدة جدار الحماية
للمنفذ 8000. لا تعطل جدار الحماية كاملًا. خادم `runserver` للتطوير المحلي فقط؛ الجلسات عبر HTTP للاختبار المحلي،
واستخدم HTTPS عند النشر الحقيقي.

## الاختبارات والتحقق

```bash
python manage.py test --verbosity 2
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py collectstatic --noinput
```

CI يكرر تثبيت التبعيات، وتطبيق migrations، وفحص النظام والمخطط والاختبارات على SQLite وPostgreSQL.
الاختبارات تشمل الصلاحيات عبر طلبات HTTP، وCSRF، واللقطات، والسياق، والاستبعاد والاسترجاع، والأدلة،
والإصدار الذري والتداخل والإلغاء والقيود الأصلية، وحماية التاريخ حتى من تعديلات ORM المباشرة.
راجع [سجل التحقق](docs/VALIDATION.md) للأدلة وحدود الاختبار، و[بروتوكول القبول](docs/HUMAN_ACCEPTANCE.md) للاختبار البشري.

## التشغيل على PostgreSQL والنشر

```bash
python -m pip install -r requirements-postgres.txt
# عيّن POSTGRES_DB وPOSTGRES_USER وPOSTGRES_PASSWORD وPOSTGRES_HOST وPOSTGRES_PORT
python manage.py migrate --noinput
```

اختيار PostgreSQL لا يرحّل تلقائيًا محتوى قاعدة SQLite؛ نقل بيانات بشرية يحتاج خطة مستقلة ونسخة احتياطية وموافقة.
للنشر: عيّن `DJANGO_DEBUG=0`، ومفتاحًا عشوائيًا، وأسماء الخوادم الصحيحة، واستعمل HTTPS ونسخًا احتياطية، ثم:

```bash
python manage.py collectstatic --noinput
python manage.py check --deploy
gunicorn config.wsgi:application --bind 127.0.0.1:8000
```

خلف reverse proxy ينهي TLS، يلزم ضبط ترويسة HTTPS الموثوقة بصورة ملائمة؛ لا تثق بترويسات forwarded من عملاء الإنترنت.
الإعداد الافتراضي لا يفترض وجود proxy. WhiteNoise يخدم الملفات الثابتة؛ لا توجد خدمة بريد أو رفع مرفقات مطلوبة.

لا يوجد نشر Sites لهذا التطبيق: البيئة المتاحة تستضيف Cloudflare Workers، بينما التطبيق المطلوب Django تقليدي
والمستودع محصور في هذا المشروع. لم يُنشأ مستودع بديل. `package.json` وأداتا `tools/*qa*` و`render_browser_fixtures.py`
تخص فحص التخطيط فقط، وليست واجهة بديلة أو خادم التطبيق.

## دورة الاستخدام

1. الإدارة تضيف المؤسسات والمراجع المشتركة والأدلة.
2. المفتش ينشئ زيارة؛ يبدأ نطاقها فارغًا وتُجمّد نسخة المرجع تلقائيًا.
3. يضيف فرعًا أو وصفًا أو بندًا، أو محتوى محليًا، أو يطبق دليلًا اختياريًا.
4. الإدارة تنشئ مسودة تكليف لزيارة موجودة ثم تصدرها؛ القيود تظهر للمفتش بعد الإصدار فقط.
5. يسجل المفتش النتائج والقيم والملاحظات، ويمكنه الاستبعاد والاسترجاع حيث تسمح القيود.
6. الإكمال يثبت السجل نهائيًا، ويُمنع عند نقص المتطلبات الإلزامية. العناصر الاختيارية غير المنجزة لا تمنعه.
7. التصدير JSON متاح للمفتش صاحب الزيارة وللإدارة، ومتطابق بين التصديرات إن لم تتغير المسودة.

تعديل مرجع أو حذفه لا يغير الزيارات. الاقتراح للتعميم فعل مستقل في المرجع الشخصي؛ قبول الإدارة ينشئ مرجعًا مشتركًا جديدًا.
لا يوجد نمط عام حر/موجه/مقيد للزيارة، ولا مرجع عالمي وحيد.

## بنية المستودع والتوثيق

- `inspections/models.py`: كيانات المجال وقيود قاعدة البيانات.
- `inspections/services/`: المراجع والزيارات والحوكمة والتصدير والمعاملات.
- `inspections/forms.py` و`views.py`: الإدخال والصلاحيات ونقاط HTTP.
- `templates/` و`static/`: صفحات عربية RTL، دون SPA أو اعتماد على JavaScript للصلاحيات.
- `inspections/migrations/`: مخطط أولي وحراس التاريخ، مع دعم SQLite وPostgreSQL.
- [القرارات](docs/DECISIONS.md)، [المعمارية والصلاحيات](docs/ARCHITECTURE.md)، [مخطط التصدير](docs/EXPORT_SCHEMA.md).
- [الحماية والنسخ الاحتياطي عند الاختبار البشري](docs/HUMAN_DATA.md).

## حدود النسخة

القبول البشري ما يزال Pending. التطبيق يحتاج اتصالًا بخادمه؛ لا يدّعي دعم العمل دون اتصال.
التقدم يحسب الوصف والبنود النشطة المختارة فقط. الفرع والسياق والاستبعاد لا يضيفون إنجازًا وهميًا.
حذف المسودة متاح لصاحبها وحده بعد التأكيد ويشمل بياناتها وتكليفاتها؛ لا حذف لزيارة مكتملة، ولا استرجاع لمسودة محذوفة من الواجهة.
لا تعدّل جدولًا أو trigger يدويًا في قاعدة إنتاج. سجلات التصدير المختومة وحراس قاعدة البيانات يحميان عمليات التطبيق، ولا يمنعان
مالك قاعدة البيانات من العبث اليدوي بمخططها أو ملفاتها.
