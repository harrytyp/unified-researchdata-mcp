"""Browser test: the lab's sample rules in the TGA form.

Covers what the form can enforce (mass limit, metallic -> alumina, acids,
consultation for metallic / MS coupling / runs above a day) and the two
declarations the requester has to make. Ends with a real submit and checks the
notes the operator gets to see in NOMAD.

How to run (token is minted server-side and never printed):

  docker exec nomad_oasis_app python3 -c "from nomad.auth.tokens import \
generate_simple_token as g; open('/tmp/tok.txt','w').write(g('<user_id>', 3600))"
  docker cp nomad_oasis_app:/tmp/tok.txt /tmp/tok.txt
  TGA_UI_TOKEN=$(ssh <host> 'cat /tmp/tok.txt') python rules_test.py
"""
import json
import os
import re
import time
import urllib.request

from playwright.sync_api import sync_playwright

URL = 'https://researchmcp.duckdns.org/nomad-oasis/api/tga-forms/'
API = 'https://researchmcp.duckdns.org/nomad-oasis/api/v1'
TOK = os.environ['TGA_UI_TOKEN']
SAMPLE = 'UI-RULES-' + str(int(time.time()))[-6:]
FAILS = []


def check(label, cond, detail=''):
    if not cond:
        FAILS.append(label)
    print(f'  [{"OK  " if cond else "FAIL"}] {label}{" - " + str(detail) if detail else ""}')


def bearer(tok=None):
    t = tok or TOK
    return {'Authorization': t if t.lower().startswith('bearer ') else 'Bearer ' + t}


def api(path):
    req = urllib.request.Request(API + path, headers=bearer())
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode())


def labelled_input(page, label):
    return page.locator(
        f'xpath=//div[contains(@class,"tga-label") and normalize-space()="{label}"]'
        '/following::input[1]').first


def set_input(page, label, value):
    """Fill a field and commit it - Quasar only emits on change/blur."""
    f = labelled_input(page, label)
    f.fill(value)
    f.press('Tab')
    page.wait_for_timeout(900)


def set_aria_input(page, aria, value):
    """Segment fields are addressed by their aria-label (see ui_units_test)."""
    f = page.locator(f'xpath=//input[contains(@aria-label,"{aria}")]').first
    f.fill(value)
    f.press('Tab')
    page.wait_for_timeout(900)


def toasts(page):
    return ' | '.join(x for x in page.eval_on_selector_all(
        '.q-notification', 'els => els.map(e => e.innerText.trim())') if x)


def click_submit(page):
    page.get_by_role('button', name='Create measurement request').first.click()


def submit_and_read_errors(page):
    """Validation errors come back immediately as toasts."""
    click_submit(page)
    page.wait_for_timeout(2500)
    return toasts(page)


def submit_and_wait(page, seconds=45):
    click_submit(page)
    body = ''
    for _ in range(seconds):
        page.wait_for_timeout(1000)
        body = page.inner_text('body')
        if 'Measurement request created' in body or 'Request submitted' in body:
            break
    return body


def switch_mass_unit(page, label):
    """The mass unit is the first select on the page (see ui_units_test)."""
    page.locator('.q-select').nth(0).click()
    page.wait_for_timeout(700)
    opts = page.locator('.q-menu .q-item__label')
    for i in range(opts.count()):
        if opts.nth(i).inner_text().strip() == label:
            opts.nth(i).click()
            page.wait_for_timeout(1200)
            return True
    return False


uid = None
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    ctx = b.new_context(viewport={'width': 1500, 'height': 1200})
    ctx.add_cookies([{'name': 'Authorization', 'value': TOK,
                      'domain': 'researchmcp.duckdns.org', 'path': '/nomad-oasis',
                      'secure': True, 'sameSite': 'Strict'}])
    page = ctx.new_page()
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)[:200]))
    page.goto(URL, wait_until='networkidle', timeout=90000)
    page.wait_for_timeout(2500)
    body = page.inner_text('body').lower()

    print('=== 1. Regeln an der richtigen Stelle ===')
    panels = page.eval_on_selector_all('.tga-panel', 'els => els.map(e => e.innerText)')
    print(f'   {len(panels)} Panels gefunden')
    sample_panel = (panels[0] if len(panels) > 0 else '').lower()
    atmo_panel = (panels[1] if len(panels) > 1 else '').lower()
    temp_panel = (panels[2] if len(panels) > 2 else '').lower()

    for needle in ('sample requirements', '5 x 5 mm', '100 mg', '50 mg',
                   'pieces or powder', 'not volatile', 'alumina crucible only',
                   'acids or bases', 'sit on the pan'):
        check(f'Sample-Panel: "{needle}"', needle in sample_panel)
    check('Atmosphaere-Regel steht im Atmosphaere-Panel',
          'nitrogen and air' in atmo_panel)
    check('Laufzeit-Regel steht im Programm-Panel',
          'longer than 1 day' in temp_panel)
    check('MS-Kopplung steht im Atmosphaere-Panel (Gasweg)',
          'mass-spectrometer' in atmo_panel)
    check('Sample-Panel wiederholt die Atmosphaere-Regel nicht',
          'nitrogen or air' not in sample_panel)
    check('Sample-Panel wiederholt die Laufzeit-Regel nicht',
          'longer than 1 day' not in sample_panel)

    print()
    print('=== 2. Pflicht-Erklaerungen blockieren ===')
    set_input(page, 'Sample name *', SAMPLE)
    set_aria_input(page, 'Target temperature', '600')
    set_aria_input(page, 'Rate', '10')
    t = submit_and_read_errors(page)
    check('ohne Erklaerung kein Submit',
          'measurement request created' not in page.inner_text('body').lower())
    check('Meldung zu den Sample-Vorgaben', 'sample requirements' in t.lower(), t[:170])
    check('Meldung zu Saeuren/Basen', 'acids or bases' in t.lower(), t[:170])

    print()
    print('=== 3. Massengrenze ===')
    set_input(page, 'Sample mass', '150')
    txt = page.inner_text('body')
    check('Hinweis ueber der 100-mg-Grenze', 'above the 100 mg limit' in txt,
          [ln for ln in txt.splitlines() if 'limit' in ln.lower()][:2])
    t = submit_and_read_errors(page)
    check('Submit ueber 100 mg blockiert', '100 mg limit' in t, t[:170])
    set_input(page, 'Sample mass', '50')
    check('50 mg gilt als im Limit', 'within the limit' in page.inner_text('body'))
    ok_unit = switch_mass_unit(page, 'g')
    check('Masseneinheit laesst sich auf g stellen', ok_unit)
    check('0.05 g bleibt im Limit',
          'within the limit' in page.inner_text('body'),
          [ln for ln in page.inner_text('body').splitlines() if 'limit' in ln.lower()][:2])
    switch_mass_unit(page, 'mg')
    set_input(page, 'Sample mass', '50')

    print()
    print('=== 4. Metallische Probe -> Alumina + Ruecksprache ===')
    page.get_by_text('Metallic sample', exact=False).first.click()
    page.wait_for_timeout(1300)
    txt = page.inner_text('body')
    check('Ruecksprache-Block erscheint', 'consultation needed' in txt.lower())
    check('Grund "metallic" genannt', 'metallic sample' in txt.lower())
    check('Kontakte stehen im Block', 'p.braun@tum.de' in txt)
    page.get_by_text('Crucible (optional)').first.click()   # expand to look inside
    page.wait_for_timeout(900)
    cruc = page.locator('.q-select').nth(1).inner_text()
    check('Tiegel im Formular auf Alumina festgelegt', 'Alumina' in cruc, cruc[:40])
    page.get_by_text('Crucible (optional)').first.click()
    page.wait_for_timeout(600)

    print()
    print('=== 5. MS-Kopplung als zweiter Grund + How-to der Rucksprache ===')
    page.get_by_text('Mass-spectrometer coupled', exact=False).first.click()
    page.wait_for_timeout(1400)
    body = page.inner_text('body')
    check('Grund "mass-spectrometer" genannt', 'mass-spectrometer' in body.lower())
    check('Rucksprache: Anleitung steht im Block', 'write to them' in body.lower())
    check('Rucksprache: Kontakte stehen im Block', 'p.braun@tum.de' in body)
    link = page.get_by_role('link', name=re.compile('prefilled email', re.I))
    check('Rucksprache: prefilled-Mail-Link vorhanden', link.count() > 0)
    if link.count():
        href = link.first.get_attribute('href') or ''
        check('Link geht an beide Kontakte',
              'p.braun' in href and 'luca.reichert' in href, href[:80])
        check('Link nennt den Probennamen', SAMPLE in href, SAMPLE)
        check('Link nennt den Grund', 'mass-spectrometer' in href or
              'mass-spectrometer' in href.lower(), href[:120])

    print()
    print('=== 6. Laufzeit > 1 Tag aus dem Programm ===')
    set_aria_input(page, 'Rate', '0.1')      # 600 °C at 0.1 °C/min ~ 96 h
    txt = page.inner_text('body')
    check('Laufzeit-Hinweis zeigt > 1 Tag', 'longer than 1 day' in txt.lower(),
          [ln for ln in txt.splitlines() if 'run time' in ln.lower()][:2])
    check('Grund "run time above 1 day" im Block', 'run time above 1 day' in txt.lower())

    print()
    print('=== 7. Mit Erklaerungen + Ruestprache-Bestaetigung ===')
    page.get_by_text('My sample meets the requirements', exact=False).first.click()
    page.get_by_text('contains no acids or bases', exact=False).first.click()
    page.wait_for_timeout(700)
    page.get_by_text('I have contacted', exact=False).first.click()
    page.wait_for_timeout(900)
    body = submit_and_wait(page)
    check('Submit gelingt', ('Measurement request created' in body
                             or 'Request submitted' in body))
    check('Abgabe-Hinweis im Erfolgsdialog',
          'Bring your sample after emailing' in body)
    m = re.search(r'Upload ID: (\S+)', body)
    uid = m.group(1) if m else None
    check('Upload-ID im Erfolgsdialog', bool(uid), uid)

    print()
    print('=== 8. Was sieht der Operator in NOMAD? ===')
    if uid:
        time.sleep(6)
        try:
            entry = api(f'/uploads/{uid}/entries')['data'][0]['entry_id']
            arch = api(f'/uploads/{uid}/archive/{entry}')
            inner = (arch.get('data') or {}).get('archive', {}).get('data', {})
            comment = inner.get('comments') or ''
            print('   comments:', repr(comment[:220]))
            check('Request notes im Eintrag', 'Request notes' in comment, comment[:160])
            check('metallisch vermerkt', 'metallic' in comment.lower())
            check('MS-Kopplung vermerkt', 'mass-spectrometer' in comment.lower())
            check('Laufzeit vermerkt', 'estimated run time' in comment.lower())
            check('Tiegel im Eintrag = Alumina',
                  str(inner.get('crucible_type', '')).lower().startswith('alumina'),
                  inner.get('crucible_type'))
            check('Gas bleibt N2/Air',
                  inner.get('gas_atmosphere') in ('N2', 'Air'),
                  inner.get('gas_atmosphere'))
        except Exception as e:
            FAILS.append(f'Eintrag nicht pruefbar: {e}')
            print('   Fehler beim Auslesen:', e)

    check('keine JS-Fehler', not errors, errors[:2])
    page.screenshot(path=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      'rules_test.png'), full_page=True)
    b.close()

print()
if uid:
    print('(Test-Upload', uid, 'muss noch aufgeraeumt werden)')
print('ERGEBNIS:', 'ALLE REGEL-CHECKS BESTANDEN' if not FAILS
      else f'{len(FAILS)} FEHLER: ' + '; '.join(FAILS))
