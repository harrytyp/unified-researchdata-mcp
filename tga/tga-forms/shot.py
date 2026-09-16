"""Only opens the live page and photographs it - no assertions.

Three moments worth looking at: the sample panel as it stands, the mass field
refusing an oversized value, and the confirmation with code + drop-off address.
"""
import os
import re

from playwright.sync_api import sync_playwright

TOK = os.environ['TGA_UI_TOKEN']
URL = 'https://researchmcp.duckdns.org/nomad-oasis/api/tga-forms/'
OUT = os.path.dirname(os.path.abspath(__file__))

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    ctx = b.new_context(viewport={'width': 1500, 'height': 1250},
                        device_scale_factor=2)
    ctx.add_cookies([{'name': 'Authorization', 'value': TOK,
                      'domain': 'researchmcp.duckdns.org', 'path': '/nomad-oasis',
                      'secure': True, 'sameSite': 'Strict'}])
    page = ctx.new_page()
    page.goto(URL, wait_until='networkidle', timeout=90000)
    page.wait_for_timeout(3000)

    panels = page.locator('.tga-panel')
    print('Panels:', panels.count())
    panels.nth(0).screenshot(path=os.path.join(OUT, 'shot_panel1.png'))
    print('wrote shot_panel1.png  (Sample + Regeln)')

    # an oversized mass: the field must refuse it, not rewrite it
    field = page.locator(
        'xpath=//div[contains(@class,"tga-label") and normalize-space()="Sample mass (mg) *"]'
        '/following::input[1]').first
    field.fill('150')
    field.press('Tab')
    page.wait_for_timeout(1200)
    panels.nth(0).screenshot(path=os.path.join(OUT, 'shot_mass_error.png'))
    print('wrote shot_mass_error.png  Wert im Feld:', field.input_value())

    # fill it validly and submit, to see what the requester is left with
    field.fill('50')
    field.press('Tab')
    page.wait_for_timeout(600)
    page.locator(
        'xpath=//div[contains(@class,"tga-label") and normalize-space()="Sample name *"]'
        '/following::input[1]').first.fill('SHOT-DEMO')
    page.locator(
        'xpath=//div[contains(@class,"tga-label") and normalize-space()="Your email *"]'
        '/following::input[1]').first.fill('shot@tum.de')
    page.locator('xpath=//input[contains(@aria-label,"Target temperature")]').first.fill('600')
    page.locator('xpath=//input[contains(@aria-label,"Rate")]').first.fill('10')
    page.wait_for_timeout(1200)
    page.get_by_text('My sample fulfils the requirements', exact=False).first.click()
    page.wait_for_timeout(700)
    page.get_by_role('button', name='Create measurement request').first.click()
    for _ in range(50):
        page.wait_for_timeout(1000)
        if 'Measurement request created' in page.inner_text('body'):
            break
    page.wait_for_timeout(1500)
    page.screenshot(path=os.path.join(OUT, 'shot_confirm.png'), full_page=True)
    body = page.inner_text('body')
    m = re.search(r'Upload ID: (\S+)', body)
    print('wrote shot_confirm.png  upload:', m.group(1) if m else '?')
    b.close()
