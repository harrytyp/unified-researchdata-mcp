"""Is the marked page visible in light mode too? Measure the colours.

The old marker was white text; in light mode the header is white, so the marker
vanished. This reads the computed colours of the active entry and the header
background in dark AND light mode, and photographs both.
"""
import os
import sys

from playwright.sync_api import sync_playwright

BASE = 'https://researchmcp.duckdns.org'
URL = BASE + '/nomad-oasis/api/tga-forms/requests'
TOKEN = os.environ['TGA_UI_TOKEN']
OUT = os.path.dirname(os.path.abspath(__file__))
fails = []


def check(label, cond, detail=''):
    if not cond:
        fails.append(label)
    print(f'  [{"OK  " if cond else "FAIL"}] {label}{" - " + str(detail) if detail else ""}')


def colours(page):
    return page.evaluate("""() => {
        const active = document.querySelector('.tga-header-btn-active');
        const header = document.querySelector('header');
        return {
            active: active ? getComputedStyle(active).color : null,
            activeText: active ? active.innerText.trim() : null,
            headerBg: header ? getComputedStyle(header).backgroundColor : null,
            bodyLight: document.body.classList.contains('body--light'),
        };
    }""")


with sync_playwright() as playwright:
    browser = playwright.chromium.launch()
    context = browser.new_context(viewport={'width': 1600, 'height': 400})
    context.add_cookies([{'name': 'Authorization', 'value': 'Bearer ' + TOKEN,
                          'domain': 'researchmcp.duckdns.org', 'path': '/nomad-oasis'}])
    page = context.new_page()
    page.goto(URL, wait_until='networkidle')
    page.wait_for_timeout(3000)

    for mode in ('dark', 'light'):
        if mode == 'light':
            page.locator('.tga-darkbtn').click()
            page.wait_for_timeout(1500)
        state = colours(page)
        print(f'--- {mode}: {state}')
        check(f'{mode}: die aktuelle Seite ist markiert',
              state['activeText'] == 'My requests', state['activeText'])
        check(f'{mode}: Markierung hat eine eigene Farbe', bool(state['active']))
        if mode == 'light':
            check('heller Modus ist aktiv', state['bodyLight'], state['bodyLight'])
            check('Markierung ist NICHT weiss',
                  '255, 255, 255' not in str(state['active']), state['active'])
        page.screenshot(path=os.path.join(OUT, f'header_{mode}.png'),
                        clip={'x': 0, 'y': 0, 'width': 1600, 'height': 80})
    browser.close()

print()
print('ERGEBNIS:', 'KOPF-FARBEN OK' if not fails else f'{len(fails)} FEHLER: {fails}')
sys.exit(1 if fails else 0)
