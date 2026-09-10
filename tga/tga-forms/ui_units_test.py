"""UI test: the TGA form as a signed-in (non-admin) user.

Verifies in a real browser:
  - the form renders for a signed-in user
  - the unit dropdowns exist (sample mass, gas flows, temperature program)
  - switching a unit rescales the value already entered (change_unit)
  - submitting through the UI creates the upload with the readable name,
    generates the .tprc and adds the operator group

The signed-in state is provided by a short-lived test token (minted
server-side), passed in via the TGA_UI_TOKEN env var so it is never printed.
"""
import json
import os
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright

URL = 'https://researchmcp.duckdns.org/nomad-oasis/api/tga-forms/'
API = 'https://researchmcp.duckdns.org/nomad-oasis/api/v1'
TOK = os.environ.get('TGA_UI_TOKEN', '')
assert TOK, 'TGA_UI_TOKEN fehlt'
FAILS = []


def check(label, cond, detail=''):
    if not cond:
        FAILS.append(label)
    print(f'  [{"OK  " if cond else "FAIL"}] {label}{(" - " + str(detail)) if detail else ""}')


def api(path, token=None):
    req = urllib.request.Request(API + path,
                                 headers={'Authorization': token or TOK})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    ctx = b.new_context(viewport={'width': 1500, 'height': 1100})
    ctx.add_cookies([{
        'name': 'Authorization', 'value': TOK, 'domain': 'researchmcp.duckdns.org',
        'path': '/nomad-oasis', 'secure': True, 'sameSite': 'Strict',
    }])
    page = ctx.new_page()
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)[:150]))
    page.goto(URL, wait_until='networkidle', timeout=90000)
    page.wait_for_timeout(3000)

    body = page.inner_text('body')
    print('Seiteninhalt (Anfang):', body[:120].replace('\n', ' | '))
    check('Formular ist sichtbar (eingeloggt)', 'Sample name' in body, body[:80])
    check('Abschnitt Atmosphere sichtbar', 'Atmosphere' in body)
    check('Abschnitt Temperature program sichtbar', 'Temperature program' in body)

    # unit dropdowns: the "Unit" labels and the program unit row
    labels = page.eval_on_selector_all(
        '.tga-label', 'els => els.map(e => e.innerText.trim())')
    for wanted in ('Unit', 'Temperature', 'Rate', 'Hold time'):
        check(f'Label "{wanted}" vorhanden', wanted in labels, labels[:14])

    selects = page.eval_on_selector_all(
        '.q-select', 'els => els.length')
    print('  Anzahl Dropdowns:', selects)
    check('mindestens 6 Dropdowns (Crucible, Gas, 3x Einheit, 1 Flow)', selects >= 6, selects)

    # segment label shows the chosen unit
    segtext = page.inner_text('.tga-seg')
    check('Segment-Label nennt die Einheit (z.B. [°C])', '°C' in segtext, segtext[:120])

    # mass value + unit switch (rescale check): enter 0.5, switch unit to g,
    # the displayed number must become 500 (the stored value stays 0.5 mg *1000)
    mass_field = page.locator(
        'xpath=//div[contains(@class,"tga-label") and normalize-space()="Sample mass"]'
        '/following::input[1]').first
    mass_field.fill('0.5')
    mass_field.press('Tab')
    page.wait_for_timeout(800)
    before = mass_field.input_value()
    # open the mass unit dropdown: it is the FIRST select on the page
    # (order: mass unit, crucible, purge gas, flow unit, temp/rate/time units, ...)
    unit_sel = page.locator('.q-select').nth(0)
    unit_sel.click()
    page.wait_for_timeout(700)
    opts = page.locator('.q-menu .q-item__label')
    labels_seen = [opts.nth(i).inner_text() for i in range(opts.count())]
    print('  Einheiten-Optionen:', labels_seen)
    (opts.nth(1) if opts.count() > 1 else opts.last).click()
    page.wait_for_timeout(1200)
    after = mass_field.input_value()
    # 0.5 mg shown in g is 0.0005 g - the physical value must be preserved
    check('Masse mg -> g rechnet um (0.5 -> 0.0005)',
          abs(float(after or 0) - 0.0005) < 1e-12, f'{before!r} -> {after!r}')
    # and back to mg: 0.0005 g -> 0.5 mg
    unit_sel.click()
    page.wait_for_timeout(700)
    page.locator('.q-menu .q-item__label').nth(0).click()
    page.wait_for_timeout(1200)
    back = mass_field.input_value()
    check('Masse g -> mg zurueck (0.0005 -> 0.5)',
          abs(float(back or 0) - 0.5) < 1e-12, f'{after!r} -> {back!r}')

    # fill a valid request and submit through the UI
    sample = 'UI-' + str(int(time.time()))[-6:]
    page.locator(
        'xpath=//div[contains(@class,"tga-label") and normalize-space()="Sample name *"]'
        '/following::input[1]').first.fill(sample)
    ramp_end = page.locator(
        'xpath=//input[contains(@aria-label,"Target temperature")]').first
    ramp_end.fill('600')
    ramp_rate = page.locator('xpath=//input[contains(@aria-label,"Rate")]').first
    ramp_rate.fill('10')
    page.wait_for_timeout(500)
    page.get_by_role('button', name='Create measurement request').first.click()
    print('  Submit geklickt, warte auf Ergebnis ...')
    ok = False
    for _ in range(40):
        page.wait_for_timeout(1500)
        txt = page.inner_text('body')
        if 'Measurement request created' in txt:
            ok = True
            break
        if 'Failed to create request' in txt or 'Error:' in txt:
            print('  Fehlermeldung:', txt[:400])
            break
    check('Submit meldet Erfolg', ok)
    if ok:
        import re
        m = re.search(r'Upload ID: (\S+)', page.inner_text('body'))
        uid = m.group(1) if m else None
        print('  upload_id:', uid)
        check('Upload-ID im Erfolgsdialog', bool(uid), uid)
        link = page.get_by_role('button', name='Open this upload in NOMAD')
        check('Link "Open this upload in NOMAD" vorhanden', link.count() > 0)
        if uid:
            up = api(f'/uploads/{uid}')['data']
            check('Upload-Name ist lesbar',
                  str(up.get('upload_name', '')).startswith(f'TGA Request: {sample}'),
                  up.get('upload_name'))
            check('Operator-Gruppe als Co-Author gesetzt',
                  bool(up.get('coauthor_groups')), up.get('coauthor_groups'))
            check('main_author = Testnutzer (Nicht-Admin)',
                  up.get('main_author') == '500a3642-1524-4205-9d0d-b750e3d780da',
                  up.get('main_author'))
            time.sleep(4)
            raw = urllib.request.urlopen(urllib.request.Request(
                f'{API}/uploads/{uid}/rawdir/', headers={'Authorization': TOK}),
                timeout=60).read()
            check('.tprc wurde erzeugt', b'.tprc' in raw)
    check('keine JS-Fehler', not errors, errors[:2])
    page.screenshot(path=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      'ui_units.png'), full_page=True)
    b.close()

print()
print('ERGEBNIS:', 'ALLE UI-CHECKS BESTANDEN' if not FAILS else f'{len(FAILS)} FEHLER: {FAILS}')
sys.exit(1 if FAILS else 0)
