"""What does /eln show? Teams loaded, hint text, options."""
import os
import subprocess
import sys

from playwright.sync_api import sync_playwright

BASE = 'https://researchmcp.duckdns.org/nomad-oasis/api/tga-forms'
USER = '41875c3d-785d-4c2f-a7f5-1c81e6290276'

out = subprocess.run(
    ['docker', 'exec', 'nomad_oasis_app', 'python3', '-c',
     'from nomad.auth.tokens import generate_simple_token as g; '
     f'print(g("{USER}", 900))'], capture_output=True, text=True, check=True)
token = out.stdout.strip().splitlines()[-1]

with sync_playwright() as playwright:
    browser = playwright.chromium.launch()
    context = browser.new_context(viewport={'width': 1500, 'height': 1200})
    context.add_cookies([{'name': 'Authorization', 'value': 'Bearer ' + token,
                          'domain': 'researchmcp.duckdns.org', 'path': '/nomad-oasis'}])
    page = context.new_page()
    page.goto(BASE + '/eln', wait_until='networkidle')
    page.wait_for_timeout(7000)

    print('--- Selects auf der Seite:', page.eval_on_selector_all(
        '.q-select', 'els => els.map(e => e.innerText.trim().slice(0, 60))'))
    print('--- Team-Hinweis:', page.eval_on_selector_all(
        '.text-xs', 'els => els.map(e => e.innerText.trim())')[:3])
    print('--- Body-Ausschnitt:', page.inner_text('body')[:400].replace('\n', ' | '))

    selects = page.query_selector_all('.q-select')
    if selects:
        selects[0].click()
        page.wait_for_timeout(2500)
        items = page.eval_on_selector_all('.q-item', 'els => els.map(e => e.innerText.trim())')
        print('--- Eintraege im Menue:', items)
    page.screenshot(path='eln_debug.png')
    browser.close()
sys.exit(0)
