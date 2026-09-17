"""Does a URL-encoded cookie break the ELN download?

NOMAD's GUI writes the Authorization cookie URL-encoded ("Bearer%20eyJ..."). The
session panel decodes it (app.fresh_token does urllib.parse.unquote), the download
endpoint did not - a 401 that then looked like "session expired".
"""
import subprocess
import sys
import urllib.parse

from playwright.sync_api import sync_playwright

BASE = 'https://researchmcp.duckdns.org'
UPLOAD = 'KAw7d5rKQJquiH50cz5fPw'          # hat eine Messung, Paket ist baubar
USER = '41875c3d-785d-4c2f-a7f5-1c81e6290276'


def mint(seconds=900):
    out = subprocess.run(
        ['docker', 'exec', 'nomad_oasis_app', 'python3', '-c',
         'from nomad.auth.tokens import generate_simple_token as g; '
         f'print(g("{USER}", {seconds}))'], capture_output=True, text=True, check=True)
    return out.stdout.strip().splitlines()[-1]


token = mint()
encoded = urllib.parse.quote('Bearer ' + token)

with sync_playwright() as playwright:
    browser = playwright.chromium.launch()
    for label, value in (('so wie die GUI schreibt (roh)', 'Bearer ' + encoded),
                         ('roh, ohne URL-Kodierung', 'Bearer ' + token),
                         ('nur Token, ohne Bearer', token)):
        context = browser.new_context()
        context.add_cookies([{'name': 'Authorization', 'value': value,
                              'domain': 'researchmcp.duckdns.org', 'path': '/nomad-oasis'}])
        # context.request schickt dieselben Cookies, startet aber keinen Download.
        response = context.request.get(f'{BASE}/eln/{UPLOAD}')
        raw = response.body()
        head = raw[:40].decode('utf-8', 'replace').replace('\n', ' ') if len(raw) < 2000 else 'ZIP'
        print(f'  {label:30} -> HTTP {response.status}'
              f' | {len(raw)} B | {response.headers.get("content-type", "")} | {head}')
        context.close()
    browser.close()
sys.exit(0)
