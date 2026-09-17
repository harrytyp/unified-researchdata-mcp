"""The three fixes from the last round: download, theme across tabs, consent.

1. /eln/<upload> must work with the cookie as NOMAD writes it (URL-encoded).
2. The dark/light choice must survive switching to another tab.
3. Email notifications need a consent tick; without it nothing is sent and the
   settings do not change.
"""
import json
import os
import subprocess
import sys
import urllib.parse

from playwright.sync_api import sync_playwright

BASE = 'https://researchmcp.duckdns.org'
FORMS = BASE + '/nomad-oasis/api/tga-forms'
UPLOAD = 'KAw7d5rKQJquiH50cz5fPw'
USER = '41875c3d-785d-4c2f-a7f5-1c81e6290276'      # kolja.knodel (admin)
fails = []


def check(label, condition, detail=''):
    print(f'  [{"OK  " if condition else "FAIL"}] {label}'
          + (f' - {str(detail)[:120]}' if detail else ''))
    if not condition:
        fails.append(label)


def mint(seconds=1800):
    out = subprocess.run(
        ['docker', 'exec', 'nomad_oasis_app', 'python3', '-c',
         'from nomad.auth.tokens import generate_simple_token as g; '
         f'print(g("{USER}", {seconds}))'], capture_output=True, text=True, check=True)
    return out.stdout.strip().splitlines()[-1]


def server_settings():
    out = subprocess.run(['docker', 'exec', 'tga-forms', 'python3', '-c',
                          'import sys, json; sys.path.insert(0, "/app"); '
                          'from notify import settings as s; '
                          'print(json.dumps({"consent": s.notifications_consent(), '
                          '"notifications": s.load_settings().get("notifications", {})}))'],
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout.strip().splitlines()[-1])


def set_server_state(notifications=None, consent="keep"):
    """Put the settings into a known state before the checks."""
    code = ('import sys, json; sys.path.insert(0, "/app"); '
            'from notify import settings as s; ')
    if notifications is not None:
        code += f's.save_settings({{"notifications": json.loads(\'{json.dumps(notifications)}\')}}); '
    if consent == "keep":
        pass
    elif consent is None:
        code += 'd = s.load_settings(); d.pop("notifications_consent", None); s._write_json(s.SETTINGS_FILE, d); '
    else:
        code += f's.set_notifications_consent({bool(consent)}); '
    code += 'print("ok")'
    subprocess.run(['docker', 'exec', 'tga-forms', 'python3', '-c', code], check=False)


token = mint()

with sync_playwright() as playwright:
    browser = playwright.chromium.launch()

    # ── 1) Download mit dem Cookie, wie die GUI ihn schreibt ────────────────
    for label, value in (('URL-kodiert (wie die GUI schreibt)',
                          urllib.parse.quote('Bearer ' + token)),
                         ('schon dekodiert', 'Bearer ' + token)):
        context = browser.new_context()
        context.add_cookies([{'name': 'Authorization', 'value': value,
                              'domain': 'researchmcp.duckdns.org', 'path': '/nomad-oasis'}])
        response = context.request.get(f'{BASE}/eln/{UPLOAD}')
        check(f'Download mit {label}', response.status == 200,
              f'HTTP {response.status}, {response.headers.get("content-type", "")}, '
              f'{len(response.body())} B')
        context.close()

    # ── 2) Dark/Light ueber Tabs hinweg ─────────────────────────────────────
    context = browser.new_context(viewport={'width': 1400, 'height': 900})
    context.add_cookies([{'name': 'Authorization', 'value': 'Bearer ' + token,
                          'domain': 'researchmcp.duckdns.org', 'path': '/nomad-oasis'}])
    page = context.new_page()
    page.goto(FORMS + '/requests', wait_until='networkidle')
    page.wait_for_timeout(4000)
    first = page.eval_on_selector('body', 'e => e.className')
    page.click('.tga-darkbtn')
    page.wait_for_timeout(1500)
    after = page.eval_on_selector('body', 'e => e.className')
    check('Der Schalter wechselt den Modus', first != after, f'{first} -> {after}')

    other = context.new_page()                     # zweiter Tab, gleicher Browser
    other.goto(FORMS + '/requests', wait_until='networkidle')
    other.wait_for_timeout(4000)
    third = other.eval_on_selector('body', 'e => e.className')
    check('Der neue Tab hat denselben Modus',
          ('dark' in third) == ('dark' in after), f'{after} -> {third}')

    other.click('.tga-darkbtn')                    # zurueckstellen
    other.wait_for_timeout(1200)
    restored = other.eval_on_selector('body', 'e => e.className')
    check('Zurueckstellen wirkt auch im ersten Tab',
          ('dark' in restored) == ('dark' in first), f'{third} -> {restored}')
    page.reload(wait_until='networkidle')
    page.wait_for_timeout(3500)
    check('Nach dem Neuladen bleibt der Modus',
          ('dark' in page.eval_on_selector('body', 'e => e.className')) == ('dark' in first))
    other.screenshot(path=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       'theme_tab.png'))
    other.close()
    page.close()

    # ── 3) Einwilligung fuer E-Mail-Benachrichtigungen ───────────────────────
    # Bekannter Ausgangszustand: Ereignisse an, keine Einwilligung.
    set_server_state(notifications={key: True for key in (
        'request_created_operator', 'request_created_user', 'results_ready_user',
        'results_ready_operator', 'moved_to_elabftw', 'processing_failed_operator')},
        consent=None)
    page = context.new_page()
    page.goto(FORMS + '/admin', wait_until='networkidle')
    page.wait_for_timeout(5000)
    consent = page.locator('.q-checkbox:has-text("GDPR")').first
    events = page.locator('.q-checkbox:has-text("operators"), '
                          '.q-checkbox:has-text("requester")')
    check('Der Einwilligungs-Haken steht im Backend', consent.count() > 0)
    check('Die Ereignis-Haken sind da', events.count() >= 5, str(events.count()))
    check('Er startet ungesetzt', 'true' not in (consent.get_attribute('aria-checked') or ''),
          consent.get_attribute('aria-checked'))

    # Die Seite hat mehrere SAVE-Knoepfe - dieser gehoert zu den Benachrichtigungen.
    save_button = page.locator(
        '.tga-panel:has-text("Which event notifies whom") button:has-text("SAVE")').first

    before = server_settings()
    events.first.click()                          # ein Ereignis umschalten
    page.wait_for_timeout(400)
    save_button.click()
    page.wait_for_timeout(3000)
    after = server_settings()
    check('Ohne Haken aendert sich nichts',
          after['notifications'] == before['notifications'],
          f"{before['notifications']} -> {after['notifications']}")
    check('und die Einwilligung bleibt aus', not after['consent'].get('given'))

    consent.click()                               # Haken setzen
    page.wait_for_timeout(500)
    check('Der Haken ist jetzt gesetzt',
          'true' in (consent.get_attribute('aria-checked') or ''),
          consent.get_attribute('aria-checked'))
    save_button.click()
    page.wait_for_timeout(3000)
    stored = server_settings()
    check('Mit Haken wird die Einwilligung festgehalten',
          stored['consent'].get('given') is True, str(stored['consent']))
    check('Zeitpunkt und Name stehen dabei',
          bool(stored['consent'].get('at')) and bool(stored['consent'].get('by')),
          str(stored['consent']))
    page.screenshot(path=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      'consent_box.png'), full_page=True)

    consent.click()                               # Widerruf
    page.wait_for_timeout(500)
    save_button.click()
    page.wait_for_timeout(3000)
    revoked = server_settings()
    check('Ein Widerruf geht durch', not revoked['consent'].get('given'), str(revoked['consent']))
    check('und schaltet die Benachrichtigungen ab',
          not any(revoked['notifications'].values()), str(revoked['notifications']))

    # Ausgangszustand wiederherstellen - ohne die Einwilligung zu behaupten, die
    # Entscheidung darueber gehoert dem Betreiber.
    set_server_state(notifications=before['notifications'], consent=None)
    restored = server_settings()
    check('Ereignisse stehen wieder wie vorher',
          restored['notifications'] == before['notifications'], str(restored['notifications']))
    page.close()
    browser.close()

print()
print('ERGEBNIS:', 'ALLE DREI OK' if not fails else f'{len(fails)} FEHLER: {fails}')
sys.exit(1 if fails else 0)
