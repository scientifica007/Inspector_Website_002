"""Optional supervised layout preview, entirely separate from Django runtime."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--host', default='0.0.0.0')
parser.add_argument('--port', type=int, default=4173)
parser.add_argument('--strictPort', action='store_true', help='Accepted for supervised preview compatibility; binding is always strict.')
args = parser.parse_args()
root = Path(__file__).resolve().parent.parent / 'test-results' / 'browser'
if not (root / 'index.html').exists():
    raise SystemExit('Run .venv/bin/python tools/render_browser_fixtures.py first.')
ThreadingHTTPServer((args.host, args.port), partial(SimpleHTTPRequestHandler, directory=str(root))).serve_forever()
