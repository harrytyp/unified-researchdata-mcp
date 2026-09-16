"""Do the short links land on the right pages, with the NOMAD session?

Every address is opened the way a user would (browser, login cookie) and the
visible content is checked - a 301 that lands on a login page would be useless.
"""
import os
import sys
import urllib.request
import json

from playwright.sync_api import sync_playwright

BASE = 'https://researchmcp.duckdns.org'
API = BASE + '/nomad-oasis/api/v1'
TOKEN = os.environ['TGA_UI_TOKEN']
FAILS = []


def check(label, cond, detail=''):
    if not cond:
        FAILS.append(label)
    print(f'  [{"OK  " if cond else "FAIL"}] {label}{" - " + str(detail) if detail else ""}')


def api(path):
    request = urllib.request.Request(API + path, headers={
        'Authorization': 'Bearer ' + TOKEN, 'Accept': 'application/json'})
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.loads(response.read().decode())


listing = api('/uploads?page_size=5&order=desc')
data = listing.get('data') or {}
uploads = data.get('uploads') if isinstance(data, dict) else data
upload_id = uploads[0]['upload_id'] if uploads else ''
print('Upload fuer den Download-Test:', upload_id)

with sync_playwright() as playwright:
    browser = playwright.chromium.launch()
    context = browser.new_context(viewport={'width': 1400, 'height': 1000})
    context.add_cookies([{'name': 'Authorization', 'value': 'Bearer ' + TOKEN,
                          'domain': 'researchmcp.duckdns.org', 'path': '/nomad-oasis'}])
    page = context.new_page()

    for path, needle in (('/tga', 'New measurement request'),
                         ('/requests', 'My measurement requests'),
                         ('/eln', 'eLabFTW'),
                         ('/admin', 'settings')):
        page.goto(BASE + path, wait_until='networkidle')
        page.wait_for_timeout(3500)
        body = page.inner_text('body')
        check(f'{path} zeigt die richtige Seite', needle.lower() in body.lower(),
              f'url={page.url.replace(BASE, "")[:70]}')
        check(f'{path} haengt nicht im Login', 'log in' not in body.lower()[:400])

    response = context.request.get(f'{BASE}/eln/{upload_id}')
    check('kurzer Download-Link liefert das Paket',
          response.status == 200 and 'zip' in (response.headers.get('content-type') or ''),
          f'{response.status} {response.headers.get("content-type")}')

    print()
    print('   Links, die wir in Mails ausgeben:')
    print(f'     Eintrag (NOMAD GUI): {BASE}/nomad-oasis/gui/user/uploads/upload/id/<upload_id>')
    print(f'     Paket-Download     : {BASE}/eln/<upload_id>')
    print(f'     Antragsseite       : {BASE}/requests')
    print(f'     ELN-Ziel           : {BASE}/eln')
    print(f'     Einstellungen      : {BASE}/admin')
    browser.close()

print()
print('ERGEBNIS:', 'ALLE LINK-CHECKS BESTANDEN' if not FAILS else f'{len(FAILS)} FEHLER: {FAILS}')
sys.exit(1 if FAILS else 0)
