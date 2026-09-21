"""Render real authenticated Django responses for read-only browser layout QA.

No authentication bypass is installed in the application. Interactive state-changing
flows are separately tested against the real HTTP views in inspections/tests.
The fixtures contain fictional demo data only and must never be deployed.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()
from django.test import Client, override_settings
from inspections.models import User, Visit, Reference, Assignment


def main():
    destination = ROOT / 'test-results' / 'browser'
    destination.mkdir(parents=True, exist_ok=True)
    pages = []
    client = Client()
    with override_settings(ALLOWED_HOSTS=['testserver']):
        for role in ['inspector', 'admin']:
            actor = User.objects.get(username='demo_' + role)
            client.force_login(actor)
            draft = Visit.objects.filter(owner__username='demo_inspector', status='DRAFT').order_by('date').first()
            reference = Reference.objects.filter(visibility='SHARED').first()
            assignment = Assignment.objects.filter(visit=draft, status='ISSUED').first()
            routes = {'dashboard': '/', 'references': '/references/', 'institutions': '/institutions/',
                'guides': '/guides/', 'assignments': '/assignments/', 'visit-new': '/visits/new/'}
            routes.update({f'visit-{tab}': f'/visits/{draft.pk}/?tab={tab}' for tab in ['execute', 'scope', 'guides', 'assignments']})
            if role == 'admin':
                routes['assignment-new'] = f'/assignments/new/{draft.pk}/'
                routes['reference-edit'] = f'/references/{reference.pk}/edit/'
                routes['guide-new'] = f'/guides/new/{reference.pk}/'
            for name, route in routes.items():
                response = client.get(route)
                if response.status_code != 200:
                    raise RuntimeError(f'{role} {route}: HTTP {response.status_code}')
                filename = role + '-' + name + '.html'
                content = response.content.decode().replace('/static/', '/assets/')
                # Prevent state-changing submissions from this static QA surface.
                content = content.replace('</body>', '<script>document.querySelectorAll("form").forEach(f=>f.addEventListener("submit",e=>e.preventDefault()));</script></body>')
                (destination / filename).write_text(content)
                pages.append(filename)
    import shutil
    shutil.copytree(ROOT / 'static', destination / 'assets', dirs_exist_ok=True)
    links = ''.join(f'<option value="{page}">{page}</option>' for page in pages)
    html = '''<!doctype html><html lang="en"><meta charset="utf-8"><title>Inspector 002 — layout QA</title>
<style>body{font:16px Arial;background:#dce3e8;margin:16px}header{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px}select,button{font:inherit;padding:8px}iframe{display:block;border:0;height:1100px;background:white}label{display:flex;align-items:center;gap:8px}</style>
<header><label>Page <select id="page">''' + links + '''</select></label><label>Viewport <select id="width"><option>360</option><option>390</option><option>768</option><option selected>1280</option></select></label><button id="apply">Show</button></header>
<iframe id="preview" title="Application preview" src="inspector-dashboard.html" width="1280"></iframe>
<script>
const params=new URLSearchParams(location.search), page=document.getElementById('page'), width=document.getElementById('width'), preview=document.getElementById('preview');
if([...page.options].some(o=>o.value===params.get('page'))) page.value=params.get('page');
if([...width.options].some(o=>o.value===params.get('width'))) width.value=params.get('width');
preview.width=width.value; preview.src=page.value;
document.getElementById('apply').onclick=()=>{location.search=new URLSearchParams({page:page.value,width:width.value});};
</script></html>'''
    (destination / 'index.html').write_text(html)
    print(f'Rendered {len(pages)} real Django response fixtures for layout QA.')


if __name__ == '__main__':
    main()
