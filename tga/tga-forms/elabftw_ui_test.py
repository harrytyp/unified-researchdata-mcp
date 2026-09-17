"""The eLabFTW flow through the pages, with a real instance.

Checks the four things that were reported:
  1. /eln loads the teams by itself (no test connection) and keeps the choice
  2. the export dialog offers the team again
  3. after the export the link is still there - on the card, not only in the dialog
  4. the experiment really is in the chosen team
"""
import json
import os
import subprocess
import sys

from playwright.sync_api import sync_playwright

BASE = 'https://researchmcp.duckdns.org/nomad-oasis/api/tga-forms'
USER = '41875c3d-785d-4c2f-a7f5-1c81e6290276'      # kolja.knodel (admin)
TEAM = '3'
KEY = os.environ['ELABFTW_LIVE_KEY']
INSTANCE = 'https://elabftw.researchmcp.duckdns.org'
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
         f'print(g("{USER}", {seconds}))'],
        capture_output=True, text=True, check=True)
    return out.stdout.strip().splitlines()[-1]


with sync_playwright() as playwright:
    browser = playwright.chromium.launch()
    context = browser.new_context(viewport={'width': 1500, 'height': 1100})
    context.add_cookies([{'name': 'Authorization', 'value': 'Bearer ' + mint(),
                          'domain': 'researchmcp.duckdns.org', 'path': '/nomad-oasis'}])
    page = context.new_page()

    # ── 1) /eln: Teams laden von selbst ─────────────────────────────────────
    page.goto(BASE + '/eln', wait_until='networkidle')
    page.wait_for_timeout(5000)
    check('Team-Auswahl ist ein Dropdown', bool(page.query_selector('.q-select')))
    hint = page.inner_text('body').lower()
    check('Teams wurden von selbst geladen (ohne Test connection)',
          'available to this api key' in hint, hint[:0])
    # Das Menue einmal oeffnen und den Eintrag anklicken.
    page.click('.q-select')
    page.wait_for_timeout(2000)
    options = page.eval_on_selector_all('.q-item', 'els => els.map(e => e.innerText.trim())')
    check('Menue listet die Teams des Keys',
          any('Probe' in o for o in options) and len(options) >= 2, str(options[:6]))
    page.click('.q-item:has-text("Probe")')
    page.wait_for_timeout(600)
    check('Auswahl steht auf Team 3',
          '3 - Probe' in page.inner_text('.q-select'), page.inner_text('.q-select')[:40])
    page.click('text=SAVE')
    page.wait_for_timeout(2500)
    body = page.inner_text('body')
    check('Auswahl gespeichert', 'Saved' in body, body[:80].replace('\n', ' | '))
    page.screenshot(path=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'eln_teams.png'))
    page.close()

    # ── 2) /requests: Export mit Team-Auswahl ───────────────────────────────
    page = context.new_page()
    page.goto(BASE + '/requests', wait_until='networkidle')
    page.wait_for_timeout(6000)
    buttons = page.query_selector_all('button:has-text("SEND TO ELABFTW"), button:has-text("SEND AGAIN")')
    check('Ein Antrag mit Messung hat den Export-Knopf', bool(buttons), str(len(buttons)))
    if not buttons:
        browser.close()
        print()
        print('ERGEBNIS:', f'{len(fails)} FEHLER: {fails}')
        sys.exit(1)

    buttons[0].click()
    page.wait_for_timeout(4000)
    dialog = page.inner_text('.q-dialog')
    check('Dialog bietet das Team an', 'Team' in dialog, dialog[:150].replace('\n', ' | '))
    check('Dialog nennt das Ziel-Team mit Namen', 'Probe' in dialog, dialog[:150].replace('\n', ' | '))

    # das Team im Dialog auf 3 stellen
    selects = page.query_selector_all('.q-dialog .q-select')
    check('Der Dialog zeigt die Team-Auswahl', bool(selects), str(len(selects)))
    if selects:
        selects[0].click()
        page.wait_for_timeout(2000)
        # Quasar haengt das Menue an den Body, nicht in den Dialog.
        page.click('.q-item:has-text("Probe")')
        page.wait_for_timeout(600)
    page.click('.q-dialog button:has-text("SEND NOW")')
    result = ''
    for _ in range(30):                              # Export dauert: Anlegen + Figur
        page.wait_for_timeout(3000)
        try:
            result = page.inner_text('.q-dialog')
        except Exception:
            result = '[Dialog geschlossen] ' + page.inner_text('body')[-300:]
        if 'Exported' in result or 'Export failed' in result or 'geschlossen' in result:
            break
    check('Export meldet das Team', 'Exported to team 3' in result, result[:200].replace('\n', ' | '))
    import re as _re
    found = _re.search(r'experiments\.php\?mode=view&id=(\d+)', result)
    exported_id = found.group(1) if found else ''
    check('Experiment-ID aus dem Dialog', bool(exported_id), str(exported_id))
    check('Der Link steht im Dialog', 'experiments.php' in result, result[:200].replace('\n', ' | '))
    page.screenshot(path=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'export_dialog.png'))
    page.click('.q-dialog button:has-text("CLOSE")')
    page.wait_for_timeout(3000)
    page.reload(wait_until='networkidle')
    page.wait_for_timeout(6000)
    card = page.inner_text('body')
    # Quasar schreibt Zwischentitel in Grossbuchstaben, und der Link steht im href.
    links = page.eval_on_selector_all('.tga-export-list a', 'els => els.map(e => e.href)')
    check('Nach dem Neuladen steht der Export auf der Karte',
          'IN ELABFTW' in card and 'experiments.php' in ''.join(links),
          ' | '.join(links)[:150])
    check('Die Karte nennt das Team', 'Team 3' in card)
    page.screenshot(path=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'card_exports.png'),
                    full_page=True)
    browser.close()

# ── aufraeumen: das Test-Experiment wieder loeschen, Eintrag entfernen ───────
import requests  # noqa: E402
created = [i for i in (exported_id,) if i]
for experiment in created:
    response = requests.delete(f'{INSTANCE}/api/v2/experiments/{experiment}',
                               headers={'Authorization': KEY}, timeout=30)
    check(f'Test-Experiment {experiment} geloescht', response.status_code < 400,
          f'HTTP {response.status_code}')
    subprocess.run(['docker', 'exec', 'tga-forms', 'python3',
                    '/app/cleanup_export.py', experiment], check=False)

print()
print('ERGEBNIS:', 'UI-FLOW OK' if not fails else f'{len(fails)} FEHLER: {fails}')
sys.exit(1 if fails else 0)
