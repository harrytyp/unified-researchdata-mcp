"""The other half of the fix: the browser's cookie is fresh, our websocket
still holds the stale one.

That is the normal case in the lab - NOMAD's GUI keeps refreshing the
Authorization cookie while the form is being filled. The page-load copy is
stale, so the submit used to fail with 401 even though the browser had a
perfectly valid token. fresh_token() reads the cookie from the browser at
submit time, so this must now succeed.

Steps: open the form with a short-lived token -> let it expire -> replace the
cookie in the browser with a fresh one (what the GUI does) -> submit.

How to run (both tokens are minted server-side and never printed):

  docker exec nomad_oasis_app python3 -c "from nomad.auth.tokens import \
generate_simple_token as g; u='<user_id>'; \
open('/tmp/stale.txt','w').write(g(u, 45)); open('/tmp/fresh.txt','w').write(g(u, 3600))"
  docker cp nomad_oasis_app:/tmp/stale.txt /tmp/stale.txt
  docker cp nomad_oasis_app:/tmp/fresh.txt /tmp/fresh.txt
  TGA_STALE_TOKEN=$(ssh <host> 'cat /tmp/stale.txt') \
  TGA_FRESH_TOKEN=$(ssh <host> 'cat /tmp/fresh.txt') python fresh_token_test.py
"""
import os
import re
import sys
import time

from playwright.sync_api import sync_playwright

URL = 'https://researchmcp.duckdns.org/nomad-oasis/api/tga-forms/'
STALE = os.environ['TGA_STALE_TOKEN']    # ~45 s lifetime
FRESH = os.environ['TGA_FRESH_TOKEN']    # 1 h lifetime
SAMPLE = 'FRESH-' + str(int(time.time()))[-6:]
fails = []


def cookie(value):
    return {'name': 'Authorization', 'value': value, 'domain': 'researchmcp.duckdns.org',
            'path': '/nomad-oasis', 'secure': True, 'sameSite': 'Strict'}


with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    ctx = b.new_context(viewport={'width': 1400, 'height': 1000})
    ctx.add_cookies([cookie(STALE)])
    page = ctx.new_page()
    page.goto(URL, wait_until='networkidle', timeout=90000)
    page.wait_for_timeout(2000)
    if 'Sample name' not in page.inner_text('body'):
        print('Token war beim Laden schon ungueltig - Abbruch')
        b.close()
        sys.exit(2)
    print('1. Formular geladen (Token damals gueltig)')

    page.locator(
        'xpath=//div[contains(@class,"tga-label") and normalize-space()="Sample name *"]'
        '/following::input[1]').first.fill(SAMPLE)
    ramp_end = page.locator('xpath=//input[contains(@aria-label,"Target temperature")]').first
    ramp_end.fill('500')
    ramp_end.press('Tab')
    page.locator('xpath=//input[contains(@aria-label,"Rate")]').first.fill('5')
    page.locator('xpath=//input[contains(@aria-label,"Rate")]').first.press('Tab')
    print('2. Formular ausgefuellt, warte auf Ablauf des alten Tokens ...')
    page.wait_for_timeout(60000)

    # the GUI refreshing the cookie while the page stays open
    ctx.add_cookies([cookie(FRESH)])
    print('3. Cookie im Browser erneuert (wie es die NOMAD-GUI tut)')

    page.get_by_role('button', name='Create measurement request').first.click()
    txt, uid = '', None
    for _ in range(45):
        page.wait_for_timeout(1500)
        txt = page.inner_text('body')
        m = re.search(r'Upload ID: (\S+)', txt)
        if m:
            uid = m.group(1)
        if 'Measurement request created' in txt or 'NOMAD session expired' in txt:
            break
    if 'Measurement request created' in txt:
        print('   OK: Upload wurde erstellt - der frische Cookie wurde benutzt')
        print('   upload_id:', uid)
    else:
        fails.append('Submit mit erneuertem Cookie schlug fehl')
        print('   FEHLER - Body:', txt[-300:].replace('\n', ' | '))
    b.close()

if not fails and uid:
    print()
    print('(Test-Upload', uid, 'muss noch aufgeraeumt werden)')
print()
print('ERGEBNIS:', 'FRISCHER COOKIE WIRD BENUTZT' if not fails else 'FEHLER: ' + '; '.join(fails))
sys.exit(1 if fails else 0)
