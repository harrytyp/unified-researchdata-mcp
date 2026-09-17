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


def page_goto(page, url):
    page.goto(url, wait_until='networkidle')
    page.wait_for_timeout(5000)
    return page.inner_text('body')


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

    # ── 3) Zustimmung im Antragsformular (optional, pro Antrag) ─────────────
    page = context.new_page()
    page.goto(FORMS + '/', wait_until='networkidle')
    page.wait_for_timeout(5000)
    box = page.locator('.q-checkbox:has-text("Inform me by email")').first
    check('Der Haken steht im Antragsformular', box.count() > 0)
    check('Er ist nicht vorab angehakt',
          'true' not in (box.get_attribute('aria-checked') or ''),
          box.get_attribute('aria-checked'))
    form_text = page.inner_text('body')
    check('Der Text nennt es optional und sagt, wofuer es ist',
          'optional' in form_text.lower() and 'results are ready' in form_text.lower())
    # Das Formular ist lang: erst hinscrollen, sonst wartet der Klick auf die
    # Sichtbarkeit und laeuft in den Timeout.
    box.scroll_into_view_if_needed()
    page.wait_for_timeout(500)
    box.click(timeout=10000)
    page.wait_for_timeout(600)
    check('Er laesst sich setzen', 'true' in (box.get_attribute('aria-checked') or ''),
          box.get_attribute('aria-checked'))
    # Erst danach weg navigieren - der Backend-Check laedt eine andere Seite.
    backend = page_goto(page, FORMS + '/admin')
    check('Die Einwilligung steht nicht mehr im Backend', 'GDPR' not in backend)
    page.screenshot(path=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      'consent_in_form.png'), full_page=True)
    page.close()
    browser.close()

# Der Eintrag muss die Zustimmung tragen - einmal mit, einmal ohne Haken.
code = ('import sys, json; sys.path.insert(0, "/app"); '
        'import nomad_api; '
        'base = {"sample_name": "X", "segments": []}; '
        'mit = nomad_api.build_archive(dict(base, notify_requester=True))["data"]; '
        'ohne = nomad_api.build_archive(dict(base))["data"]; '
        'print(json.dumps({"mit": mit.get("notify_requester"), '
        '"ohne": ohne.get("notify_requester")}))')
out = subprocess.run(['docker', 'exec', 'tga-forms', 'python3', '-c', code],
                     capture_output=True, text=True, check=False)
try:
    values = json.loads(out.stdout.strip().splitlines()[-1])
except Exception:
    values = {}
check('Mit Haken steht die Zustimmung im Eintrag', values.get('mit') is True, str(values))
check('Ohne Haken steht ausdruecklich False darin', values.get('ohne') is False, str(values))

print()
print('ERGEBNIS:', 'ALLE DREI OK' if not fails else f'{len(fails)} FEHLER: {fails}')
sys.exit(1 if fails else 0)
