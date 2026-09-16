"""Browser test: the lab's sample rules in the TGA form.

Covers what the form enforces (the 100 mg limit sits in the mass field,
metallic -> alumina, consultation for metallic / MS coupling / runs above a
day), the single requirements statement, the email prefilled from the login
token and the drop-off address in the confirmation. Ends with a real submit and
checks what the operator gets to see in NOMAD.

How to run (token is minted server-side and never printed):

  docker exec nomad_oasis_app python3 -c "from nomad.auth.tokens import \
generate_simple_token as g; open('/tmp/tok.txt','w').write(g('<user_id>', 7200))"
  docker cp nomad_oasis_app:/tmp/tok.txt /tmp/tok.txt
  TGA_UI_TOKEN=$(ssh <host> 'cat /tmp/tok.txt') python rules_test.py

The email prefill cannot be checked with a minted token (see section 1b); the
token decode itself is covered by test_session_email.py.'
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
# the email the test token carries; the form must prefill it by itself
EXPECT_EMAIL = os.environ.get('TGA_TEST_EMAIL', 'tga-test@tum.de')
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


def open_options(page, xpath, attempts=4):
    """Read the options of a Quasar select.

    The menu only exists in the DOM while it is open, and Quasar needs a moment
    to mount it - so this retries instead of reading an empty list.
    """
    for _ in range(attempts):
        try:
            page.locator(xpath).first.click()
        except Exception:
            pass
        page.wait_for_timeout(800)
        items = [o.strip() for o in page.locator('.q-menu .q-item').all_inner_texts()]
        if items:
            return items
        page.keyboard.press('Escape')
        page.wait_for_timeout(300)
        try:
            page.get_by_text('Crucible (optional)').first.click()
            page.wait_for_timeout(400)
        except Exception:
            pass
    return []


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
    """Click submit and watch for the outcome - collecting toasts as they come.

    A failure toast lives ~5 s; reading them only after a 45 s wait would miss
    exactly the error we are looking for.
    """
    click_submit(page)
    body = ''
    seen = []
    for _ in range(seconds):
        page.wait_for_timeout(1000)
        body = page.inner_text('body')
        note = toasts(page)
        if note and note not in seen:
            seen.append(note)
        if 'Measurement request created' in body or 'Request submitted' in body:
            break
    return body, ' | '.join(seen)


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

    for needle in ('sample requirements', '5 x 5 mm', 'aim for 50 mg',
                   'pieces or powder', 'not volatile', 'alumina crucible only',
                   'acids/bases', 'sit on the pan'):
        check(f'Sample-Panel: "{needle}"', needle in sample_panel)
    check('Sample-Panel schreibt die 100-mg-Grenze NICHT mehr hin',
          '100 mg' not in sample_panel)
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
    print('=== 1b. E-Mail des Senders ===')
    email_field = labelled_input(page, 'Your email *')
    check('E-Mail-Feld vorhanden', email_field.count() > 0)
    prefill = email_field.input_value() if email_field.count() else ''
    # A minted test token is a NOMAD simple token and cannot carry an email:
    # NOMAD treats any JWT with more than {user, exp} as a Keycloak token and
    # then demands a key it can verify against the realm. So no prefill here -
    # the token decode itself is covered by test_session_email.py, and the
    # real login token is the one that carries the claim.
    check('kein Fantasiewert ohne E-Mail-Claim', prefill == '', prefill)
    set_input(page, 'Your email *', EXPECT_EMAIL)
    check('E-Mail laesst sich eintragen und bleibt stehen',
          labelled_input(page, 'Your email *').input_value() == EXPECT_EMAIL)

    print()
    print('=== 2. Pflichtfelder blockieren ===')
    set_input(page, 'Sample name *', SAMPLE)
    set_aria_input(page, 'Target temperature', '600')
    set_aria_input(page, 'Rate', '10')
    t = submit_and_read_errors(page)
    check('ohne Masse/Erklaerung kein Submit',
          'measurement request created' not in page.inner_text('body').lower())
    check('Meldung zur fehlenden Masse', 'sample mass' in t.lower(), t[:200])
    check('Meldung zur Erklaerung',
          'fulfils the sample requirements' in t.lower(), t[:200])

    print()
    print('=== 3. Massengrenze sitzt im Feld, nicht im Text ===')
    set_input(page, 'Sample mass (mg) *', '150')
    txt = page.inner_text('body')
    check('Feld meldet die Grenze', 'between 0 and 100 mg' in txt.lower(),
          [ln for ln in txt.splitlines() if '100' in ln][:2])
    check('Feld ist rot markiert', page.locator('.q-field--error').count() > 0)
    check('Wert wird nicht still geklemmt',
          labelled_input(page, 'Sample mass (mg) *').input_value() == '150',
          labelled_input(page, 'Sample mass (mg) *').input_value())
    t = submit_and_read_errors(page)
    check('Submit ueber 100 mg blockiert', '100 mg' in t, t[:170])
    set_input(page, 'Sample mass (mg) *', '50')
    check('50 mg wird angenommen', page.locator('.q-field--error').count() == 0)
    select_texts = [s.strip() for s in page.eval_on_selector_all(
        '.q-select', 'els => els.map(e => e.innerText)')]
    check('keine Gramm-Einheit mehr',
          not any(s == 'g' for s in select_texts), select_texts[:6])

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
    # the crucible select is addressed by its label (NiceGUI renders ui.select
    # as a <label class="q-select">, and the select indices moved when the mass
    # unit dropdown was dropped)
    cruc = page.locator(
        'xpath=//div[contains(@class,"tga-label") and normalize-space()="Crucible"]'
        '/following::*[contains(@class,"q-select")][1]').first.inner_text()
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
    print('=== 7. Erklaerung + Rucksprache-Bestaetigung -> Submit ===')
    page.get_by_text('My sample fulfils the requirements', exact=False).first.click()
    page.wait_for_timeout(600)
    page.get_by_text('I have contacted', exact=False).first.click()
    page.wait_for_timeout(900)
    body, submit_notes = submit_and_wait(page)
    if 'Measurement request created' not in body and 'Request submitted' not in body:
        print('   Was der Submit gemeldet hat:', submit_notes[:500] or '(nichts)')
    check('Submit gelingt', ('Measurement request created' in body
                             or 'Request submitted' in body))
    check('Sample-Code im Erfolgsdialog', 'write this on the sample' in body)
    for line in ('TUM School of Engineering and Design',
                 'Department of Materials Engineering',
                 'Lehrstuhl für Werkstoffwissenschaften',
                 'Boltzmannstr. 15', '85748 Garching', 'MW 2228'):
        check(f'Adresse im Erfolgsdialog: "{line}"', line in body)
    check('Adresse nur nach Absprache',
          'agreeing the drop-off' in body.lower())
    check('Kontaktadresse im Erfolgsdialog', EXPECT_EMAIL in body, EXPECT_EMAIL)
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
            check('E-Mail des Senders im Eintrag gespeichert',
                  inner.get('requester_email') == EXPECT_EMAIL,
                  inner.get('requester_email'))
        except Exception as e:
            FAILS.append(f'Eintrag nicht pruefbar: {e}')
            print('   Fehler beim Auslesen:', e)

    print()
    print('=== 6. Vorgaben der Operatoren: Tiegel, Fluesse, Programm ===')
    # 1. Aluminium-Tiegel werden nicht angeboten.
    # Die Optionen stehen als Konstante in der Seite; das Menue selbst laesst
    # sich in der zugeklappten Sektion nicht verlaesslich oeffnen.
    source = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               'app.py'), encoding='utf-8').read()
    crucibles = re.search(r'CRUCIBLES = \[(.*?)\]', source)
    listed = crucibles.group(1) if crucibles else ''
    check('Tiegelauswahl ohne Aluminum', 'luminum' not in listed, listed.strip())
    check('Alumina und Platinum bleiben waehlbar',
          'Alumina' in listed and 'Platinum' in listed, listed.strip())
    page.get_by_text('Crucible (optional)').first.click()
    page.wait_for_timeout(700)
    check('kein Aluminum im gerenderten Formular',
          'aluminum' not in page.inner_text('body').lower())
    page.keyboard.press('Escape')
    page.wait_for_timeout(400)
    # 2. Keine Tiegel-Nummer fuer den Antragsteller.
    check('kein Feld "Crucible no."',
          page.locator('xpath=//div[contains(@class,"tga-label") and '
                       'normalize-space()="Crucible no."]').count() == 0)
    # 3. Fluesse sind Vorgabe des Labors, keine Eingabe.
    body = page.inner_text('body')
    check('kein Feld "Sample flow"',
          page.locator('xpath=//div[contains(@class,"tga-label") and '
                       'normalize-space()="Sample flow"]').count() == 0)
    check('kein Feld "Balance flow"',
          page.locator('xpath=//div[contains(@class,"tga-label") and '
                       'normalize-space()="Balance flow"]').count() == 0)
    check('Fluesse stehen als Vorgabe im Formular',
          'Sample 20 mL/min' in body and 'Balance 10 mL/min' in body)
    # 4. Programm: nur Rampe und Haltezeit, keine Gasfluss-Schritte.
    check('kein Feld "Gas flow" im Programmschritt',
          page.locator('xpath=//input[contains(@aria-label,"Gas flow")]').count() == 0)
    seg_options = open_options(page, '[aria-label*="Segment type"]')
    if not seg_options:
        seg_options = open_options(page, 'xpath=//label[contains(., "Segment type")]')
    check('Segmenttypen ohne Gasfluss',
          bool(seg_options) and not any('flow' in o.lower() for o in seg_options),
          seg_options)
    check('Rampe und Haltezeit bleiben waehlbar',
          any('Ramp' in o for o in seg_options) and any('Isothermal' in o for o in seg_options),
          seg_options)
    page.keyboard.press('Escape')
    page.wait_for_timeout(400)

    print()
    print('=== 7. Slot-Vergabe (Operatoren) ===')
    page.goto(URL + 'admin')
    page.wait_for_timeout(2500)
    admin_body = page.inner_text('body')
    if 'Not enabled for this account' in admin_body:
        print('  [SKIP] Admin-Panel (der Token gehoert zu keinem Admin-Konto)')
    else:
        check('Admin: Slot-Panel vorhanden', 'Crucible slots' in admin_body)
        check('Admin: Button vergibt nach Eingangsdatum',
              'assign by registration date' in admin_body.lower())
        page.goto(URL)
        page.wait_for_timeout(2000)

    check('keine JS-Fehler', not errors, errors[:2])
    page.screenshot(path=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      'rules_test.png'), full_page=True)
    b.close()

print()
if uid:
    print('(Test-Upload', uid, 'muss noch aufgeraeumt werden)')
print('ERGEBNIS:', 'ALLE REGEL-CHECKS BESTANDEN' if not FAILS
      else f'{len(FAILS)} FEHLER: ' + '; '.join(FAILS))
