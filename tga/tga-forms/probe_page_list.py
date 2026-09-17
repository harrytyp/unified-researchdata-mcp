"""What does the request page actually show? Count the cards and their titles."""
import os
import sys

from playwright.sync_api import sync_playwright

BASE = 'https://researchmcp.duckdns.org'
URL = BASE + '/nomad-oasis/api/tga-forms/requests'
TOKEN = os.environ['TGA_UI_TOKEN']
fails = []

with sync_playwright() as playwright:
    browser = playwright.chromium.launch()
    context = browser.new_context(viewport={'width': 1500, 'height': 1200})
    context.add_cookies([{'name': 'Authorization', 'value': 'Bearer ' + TOKEN,
                          'domain': 'researchmcp.duckdns.org', 'path': '/nomad-oasis'}])
    page = context.new_page()
    page.goto(URL, wait_until='networkidle')
    page.wait_for_timeout(4000)

    titles = page.eval_on_selector_all(
        '.tga-panel .text-lg', 'els => els.map(e => e.innerText.trim())')
    print(f'{len(titles)} Karten auf der Seite')
    for title in titles[:12]:
        print(f'   {title!r}')
    empty = [t for t in titles if not t]
    if not titles:
        fails.append('keine Karten')
    if empty:
        fails.append(f'{len(empty)} Karten ohne Titel')
    if 'No requests yet.' in page.inner_text('body'):
        fails.append('Seite sagt "No requests yet."')
    print()
    print('ERGEBNIS:', 'LISTE OK' if not fails else f'FEHLER: {fails}')
    page.screenshot(path=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      'requests_list.png'), full_page=True)
    browser.close()

sys.exit(1 if fails else 0)
