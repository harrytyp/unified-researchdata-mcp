"""Only opens the live page and photographs it - no assertions.

The point is to actually look at the thing instead of reading text dumps:
screenshots of every panel plus the consultation block, so placement and
wording can be judged from the rendered page.
"""
import os

from playwright.sync_api import sync_playwright

TOK = os.environ['TGA_UI_TOKEN']
URL = 'https://researchmcp.duckdns.org/nomad-oasis/api/tga-forms/'
OUT = os.path.dirname(os.path.abspath(__file__))

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    ctx = b.new_context(viewport={'width': 1500, 'height': 1200},
                        device_scale_factor=2)
    ctx.add_cookies([{'name': 'Authorization', 'value': TOK,
                      'domain': 'researchmcp.duckdns.org', 'path': '/nomad-oasis',
                      'secure': True, 'sameSite': 'Strict'}])
    page = ctx.new_page()
    page.goto(URL, wait_until='networkidle', timeout=90000)
    page.wait_for_timeout(3000)

    panels = page.locator('.tga-panel')
    print('Panels:', panels.count())
    for i in range(panels.count()):
        panels.nth(i).scroll_into_view_if_needed()
        page.wait_for_timeout(400)
        path = os.path.join(OUT, f'shot_panel{i + 1}.png')
        panels.nth(i).screenshot(path=path)
        print('wrote', path)

    # a request that needs a consultation: metallic + MS coupling
    page.get_by_text('Metallic sample', exact=False).first.click()
    page.get_by_text('Mass-spectrometer coupled', exact=False).first.click()
    page.wait_for_timeout(1500)
    body = page.locator('text=Consultation needed').first
    body.scroll_into_view_if_needed()
    page.wait_for_timeout(600)
    path = os.path.join(OUT, 'shot_consult.png')
    page.screenshot(path=path)
    print('wrote', path)

    # what the requester sees after submitting
    page.wait_for_timeout(300)
    b.close()
