"""Reproduce the 401 a user hit: a token that is still valid when the page is
built but has expired by the time the form is submitted.

The form used to freeze the Authorization cookie at page build
(app.py: index() -> st()['auth']) and reuse it on submit. Filling a TGA
request takes longer than a keycloak access token lives, so the frozen value
is expired on submit and the user only saw the raw API error.

Expects the fix: a clear "NOMAD session expired" card with a sign-in button.

How to run (token is minted server-side and never printed):

  docker exec nomad_oasis_app python3 -c "from nomad.auth.tokens import \
generate_simple_token as g; open('/tmp/tok.txt','w').write(g('<user_id>', 40))"
  docker cp nomad_oasis_app:/tmp/tok.txt /tmp/tok.txt
  WAIT_SECONDS=50 TGA_UI_TOKEN=$(ssh <host> 'cat /tmp/tok.txt') \
      python session_expiry_test.py

WAIT_SECONDS must be longer than the token lifetime but short enough that the
socket.io connection stays warm (~60 s has proven reliable).
"""
import os
import sys

from playwright.sync_api import sync_playwright

URL = 'https://researchmcp.duckdns.org/nomad-oasis/api/tga-forms/'
TOK = os.environ['TGA_UI_TOKEN']       # minted with a SHORT lifetime
SAMPLE = 'EXPIRY-REPRO'

fails = []
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    ctx = b.new_context(viewport={'width': 1400, 'height': 1000})
    ctx.add_cookies([{
        'name': 'Authorization', 'value': TOK, 'domain': 'researchmcp.duckdns.org',
        'path': '/nomad-oasis', 'secure': True, 'sameSite': 'Strict',
    }])
    page = ctx.new_page()
    page.goto(URL, wait_until='networkidle', timeout=90000)
    page.wait_for_timeout(2000)
    body = page.inner_text('body')
    form_visible = 'Sample name' in body
    print('1. Formular sichtbar (Token beim Laden gueltig):', form_visible)
    if not form_visible:
        print('   -> Token war schon beim Laden ungueltig, Repro nicht moeglich')
        b.close()
        sys.exit(2)

    # fill the sample name
    page.locator(
        'xpath=//div[contains(@class,"tga-label") and normalize-space()="Sample name *"]'
        '/following::input[1]').first.fill(SAMPLE)
    # and the mandatory ramp values (validation blocks the submit otherwise)
    ramp_end = page.locator('xpath=//input[contains(@aria-label,"Target temperature")]').first
    ramp_end.fill('600')
    ramp_end.press('Tab')
    ramp_rate = page.locator('xpath=//input[contains(@aria-label,"Rate")]').first
    ramp_rate.fill('10')
    ramp_rate.press('Tab')
    page.wait_for_timeout(800)
    page.wait_for_timeout(500)

    print('2. warte, bis das Token abgelaufen ist ...')
    page.wait_for_timeout(int(os.environ.get('WAIT_SECONDS', '75')) * 1000)

    # submit without reloading the page (the websocket still holds the
    # page-load cookie)
    page.get_by_role('button', name='Create measurement request').first.click()
    txt = ''
    notes = []
    for _ in range(40):
        page.wait_for_timeout(1500)
        txt = page.inner_text('body')
        try:
            notes += [n.strip() for n in page.eval_on_selector_all(
                '.q-notification', 'els => els.map(e => e.innerText.trim())')]
        except Exception:
            pass
        if 'Measurement request created' in txt or 'Failed to create request' in txt:
            break
        if 'session' in txt.lower() or 'expired' in txt.lower():
            break
    import re
    m = re.search(r'Failed to create request[^\n]*', txt)
    err = m.group(0) if m else None
    print('3. Ergebnis nach dem Absenden:')
    uniq = []
    for n in notes:
        if n not in uniq:
            uniq.append(n)
    print('   Toasts:', uniq if uniq else 'keine')
    if 'NOMAD session expired' in txt:
        print('   OK: klare Meldung "NOMAD session expired" + Anmeldung angeboten')
    else:
        fails.append('keine Session-abgelaufen-Meldung')
    if 'sign in to nomad' in txt.lower():
        print('   OK: Button "Sign in to NOMAD" ist da')
    else:
        fails.append('kein Anmelde-Button im Hinweis')
    if err:
        print('   (roher API-Fehler noch als Toast:', err[:120], ')')
    print('   Body-Ende:', txt[-240:].replace('\n', ' | '))
    page.screenshot(path=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      'repro_expiry.png'), full_page=True)
    b.close()

print()
print('ERGEBNIS:', 'SESSION-HANDLING OK' if not fails else 'FEHLER: ' + '; '.join(fails))
