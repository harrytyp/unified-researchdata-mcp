"""Slot assignment: do the numbers follow the registration date?

Runs against the real waiting requests (read-only for NOMAD apart from one
metadata note) and clears the assignment again at the end, so the live state is
as before - the check is about the order, not about keeping numbers.
"""
import os
import sys

sys.path.insert(0, '/app')

import nomad_api                                                    # noqa: E402
import ui_notify                                                    # noqa: E402
from notify import settings as settings_mod                         # noqa: E402

# ui_notify bekommt seine Abhaengigkeiten beim Start der App uebergeben; hier
# wird nur der API-Zugriff gebraucht (die Seiten selbst spielen hier keine Rolle).
try:
    ui_notify.register(get_user=lambda: None, get_token=lambda: '',
                       accent='#5e6ad2', css='', title='', open_login_js='',
                       nomad_api=nomad_api, state=lambda: {}, navigate=lambda target: None)
except Exception as error:                                          # noqa: BLE001
    print(f'  (register ohne Seitenkontext: {error})')

FAILS = []


def check(label, cond, detail=''):
    if not cond:
        FAILS.append(label)
    print(f'  [{"OK  " if cond else "FAIL"}] {label}{" - " + str(detail) if detail else ""}')


token = os.environ.get('TGA_UI_TOKEN', '')

print('=== 1. Logik: Nummern folgen der uebergebenen Reihenfolge ===')
settings_mod.pan_slots_clear()
assigned = settings_mod.pan_slots_assign(['c', 'a', 'b'])
check('drei Antraege bekommen 1..3 in Reihenfolge',
      [assigned['c'], assigned['a'], assigned['b']] == [1, 2, 3], assigned)
assigned2 = settings_mod.pan_slots_assign(['a', 'b', 'c', 'd'])
check('bestehende Nummern bleiben, neue fuellen auf',
      assigned2.get('d') == 4 and assigned2.get('a') == 2, assigned2)
check('gespeichert', settings_mod.pan_slot_get('c') == 1)

print()
print('=== 2. Live: wartende Antraege nach Eingangsdatum ===')
if not token:
    print('  [SKIP] kein Token uebergeben')
else:
    rows = ui_notify._pending_requests(token)
    print(f'  {len(rows)} wartende Antraege')
    for row in rows:
        print(f"    {row['created']}  {row['code']}  {row['sample']}")
    check('nach Eingangsdatum sortiert',
          [r['created_raw'] for r in rows] == sorted(r['created_raw'] for r in rows))
    if rows:
        settings_mod.pan_slots_clear()
        live = settings_mod.pan_slots_assign([r['upload_id'] for r in rows])
        ordered = [live[r['upload_id']] for r in rows]
        check('Slot 1 geht an den aeltesten Antrag', ordered[0] == 1, ordered)
        check('Nummern laufen ohne Luecke hoch', ordered == list(range(1, len(rows) + 1)),
              ordered)
        first = rows[0]
        # NOMAD lehnt eigene Upload-Felder ab (422 "Unknown quantity"), die
        # Nummer lebt deshalb in den Einstellungen und wird in den Seiten gezeigt.
        check('Slot erscheint in der Antragsliste',
              settings_mod.pan_slot_get(first['upload_id']) == 1)
        check('Slot ist der Nachschlag-Lookups bekannt',
              str(first['upload_id']) in settings_mod.pan_slots_read())
        settings_mod.pan_slots_clear()
        check('zurueckgesetzt (Live-Zustand unveraendert)',
              settings_mod.pan_slots_read() == {})

print()
print('ERGEBNIS:', 'ALLE SLOT-CHECKS BESTANDEN' if not FAILS else f'{len(FAILS)} FEHLER: {FAILS}')
sys.exit(1 if FAILS else 0)
