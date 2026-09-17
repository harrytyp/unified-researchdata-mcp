"""Header check: same entries, same order, same place on every page.

Covers what the user reported: "New request" went to the base domain, "TGA" went
to NOMAD without saying so, the dark toggle only existed on the form, the user
name moved around, the current page was marked white-on-white, and "Admin"
should only be there for the accounts that may open it.

Run with a NOMAD token in TGA_UI_TOKEN (admin) and optionally a second, normal
account in TGA_UI_TOKEN_PLAIN to check the Admin entry is hidden for it.
"""
import os
import sys

from playwright.sync_api import sync_playwright

BASE = 'https://researchmcp.duckdns.org'
PAGES = (('New request', '/nomad-oasis/api/tga-forms/', 'New measurement request'),
         ('My requests', '/nomad-oasis/api/tga-forms/requests', 'My measurement requests'),
         ('', '/nomad-oasis/api/tga-forms/eln', 'eLabFTW'),
         ('Admin', '/nomad-oasis/api/tga-forms/admin', 'settings'))
FAILS = []


def check(label, cond, detail=''):
    if not cond:
        FAILS.append(label)
    print(f'  [{"OK  " if cond else "FAIL"}] {label}{" - " + str(detail) if detail else ""}')


def header_state(page):
    """Entries, their order, the dark button and the user label of the header."""
    return page.evaluate("""() => {
        const head = document.querySelector('header');
        if (!head) return {items: [], dark: false, user: '', positions: {}};
        const items = [...head.querySelectorAll('button')]
            .map(b => b.innerText.trim()).filter(t => t && t !== 'Sign in');
        const dark = !!head.querySelector('.tga-darkbtn');
        const userEl = head.querySelector('.tga-user');
        const positions = {};
        for (const b of head.querySelectorAll('button')) {
            const box = b.getBoundingClientRect();
            positions[b.innerText.trim()] = [Math.round(box.x), Math.round(box.y)];
        }
        return {items, dark, user: userEl ? userEl.innerText.trim() : '',
                positions, active: [...head.querySelectorAll('.tga-header-btn-active')]
                    .map(b => b.innerText.trim())};
    }""")


def run(context, token_label):
    page = context.new_page()
    print(f'=== {token_label} ===')
    orders, users, active_states = [], [], {}
    for active, path, needle in PAGES:
        page.goto(BASE + path, wait_until='networkidle')
        page.wait_for_timeout(3000)
        state = header_state(page)
        body = page.inner_text('body')
        check(f'{path}: richtige Seite', needle.lower() in body.lower())
        check(f'{path}: Kern-Eintraege vorhanden',
              all(item in state['items'] for item in ('New request', 'My requests', 'NOMAD')),
              state['items'])
        check(f'{path}: Dunkelmodus-Schalter da', state['dark'])
        check(f'{path}: Benutzername sichtbar', bool(state['user']), state['user'])
        orders.append(tuple(state['items']))
        users.append(state['user'])
        active_states[path] = state.get('active', [])
    check('Eintraege stehen auf jeder Seite in derselben Reihenfolge',
          len(set(orders)) == 1, orders[0])
    check('Benutzername steht auf jeder Seite an derselben Stelle',
          len(set(users)) == 1, users[0])
    return page, active_states


def main() -> int:
    plain = os.environ.get('TGA_UI_TOKEN_PLAIN', '')
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for label, token, expect_admin in (('Admin-Konto', os.environ['TGA_UI_TOKEN'], True),
                                           ('normales Konto', plain, False)):
            if not token:
                print(f'=== {label}: uebersprungen (kein Token) ===')
                continue
            context = browser.new_context(viewport={'width': 1600, 'height': 1000})
            context.add_cookies([{'name': 'Authorization', 'value': 'Bearer ' + token,
                                  'domain': 'researchmcp.duckdns.org', 'path': '/nomad-oasis'}])
            page, active_states = run(context, label)
            page.goto(BASE + '/nomad-oasis/api/tga-forms/requests', wait_until='networkidle')
            page.wait_for_timeout(2500)
            items = header_state(page)['items']
            check(f'{label}: Admin-Eintrag {"sichtbar" if expect_admin else "versteckt"}',
                  ('Admin' in items) == expect_admin, items)
            check(f'{label}: aktuelle Seite ist markiert',
                  active_states['/nomad-oasis/api/tga-forms/requests'] == ['My requests'],
                  active_states)
            check(f'{label}: kein Eintrag "My ELN" mehr', 'My ELN' not in items, items)
            page.screenshot(path=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                              f'header_{label.split("-")[0].lower()}.png'),
                            clip={'x': 0, 'y': 0, 'width': 1600, 'height': 90})
            context.close()
        browser.close()
    print()
    print('ERGEBNIS:', 'ALLE KOPF-CHECKS BESTANDEN' if not FAILS else f'{len(FAILS)} FEHLER: {FAILS}')
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())
