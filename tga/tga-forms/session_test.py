"""Session handling on the request list.

The complaint: the page said "The NOMAD API answered 401" and showed nothing.
Three things have to hold now:
  1. an expired session is explained (not a raw API error, not "No requests yet.")
  2. the form's own panel is used - one wording for both pages
  3. once the browser has a fresh cookie, the page comes back by itself
"""
import os
import subprocess
import sys
import time

from playwright.sync_api import sync_playwright

BASE = 'https://researchmcp.duckdns.org'
URL = BASE + '/nomad-oasis/api/tga-forms/requests'
USER = '41875c3d-785d-4c2f-a7f5-1c81e6290276'   # kolja.knodel (admin)
fails = []


def check(label, cond, detail=''):
    if not cond:
        fails.append(label)
    line = f'  [{"OK  " if cond else "FAIL"}] {label}'
    print(line + (f' - {str(detail)[:110]}' if detail else ''))


def mint(seconds):
    out = subprocess.run(
        ['docker', 'exec', 'nomad_oasis_app', 'python3', '-c',
         'from nomad.auth.tokens import generate_simple_token as g; '
         f'print(g("{USER}", {seconds}))'],
        capture_output=True, text=True, check=True)
    return out.stdout.strip().splitlines()[-1]


def set_cookie(context, token):
    context.clear_cookies()
    context.add_cookies([{'name': 'Authorization', 'value': 'Bearer ' + token,
                          'domain': 'researchmcp.duckdns.org', 'path': '/nomad-oasis'}])


def cards(page):
    return page.eval_on_selector_all('.tga-panel .text-lg',
                                     'els => els.map(e => e.innerText.trim())')


with sync_playwright() as playwright:
    browser = playwright.chromium.launch()
    context = browser.new_context(viewport={'width': 1400, 'height': 950})

    # ── 1) abgelaufene Sitzung ───────────────────────────────────────────────
    set_cookie(context, mint(1))
    time.sleep(3)
    page = context.new_page()
    page.goto(URL, wait_until='networkidle')
    page.wait_for_timeout(4000)
    body = page.inner_text('body')
    check('abgelaufen: Sitzungs-Panel statt Rohfehler',
          'nomad session expired' in body.lower()
          and 'no requests yet' not in body.lower(), body[:90].replace('\n', ' | '))
    check('abgelaufen: sagt, dass sich die Seite selbst zurueckholt',
          'reloads by itself' in body.lower())
    check('abgelaufen: Anmelde-Knopf da', 'sign in to nomad' in body.lower())
    check('abgelaufen: NICHT "No requests yet."', 'No requests yet.' not in body)

    # ── 2) frischer Cookie -> Seite kommt von selbst zurueck ────────────────
    set_cookie(context, mint(900))
    recovered = False
    for _ in range(12):                      # der Reload-JS pollt jede Sekunde
        page.wait_for_timeout(1000)
        try:
            body = page.inner_text('body')
        except Exception:
            continue
        if 'session expired' not in body.lower() and cards(page):
            recovered = True
            break
    check('frischer Cookie: Seite laedt sich selbst neu und zeigt die Antraege',
          recovered, f'{len(cards(page))} Karten')
    page.screenshot(path=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      'session_recovered.png'))
    page.close()

    # ── 3) gueltige Sitzung von Anfang an ───────────────────────────────────
    set_cookie(context, mint(900))
    page = context.new_page()
    page.goto(URL, wait_until='networkidle')
    page.wait_for_timeout(4000)
    body = page.inner_text('body')
    check('gueltig: Liste ohne Sitzungs-Panel',
          'session expired' not in body.lower() and len(cards(page)) > 0,
          f'{len(cards(page))} Karten')
    browser.close()

print()
print('ERGEBNIS:', 'SITZUNG OK' if not fails else f'{len(fails)} FEHLER: {fails}')
sys.exit(1 if fails else 0)
