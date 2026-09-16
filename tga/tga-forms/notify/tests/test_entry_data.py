"""Unit test for notify.entry_data - reading a request's data from the archive.

Runs against a real processed upload when one is given (that is the only way to
know the field names are right), and always checks the pure helpers. Usage:

  python3 test_notify_entry_data.py [upload_id]

Without an upload id it looks for the newest upload in the staging volume that
has an archive; if there is none, the checks that need one are reported as
skipped instead of failing.
"""
import glob
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
# Die Tests liegen in notify/tests; fuer 'from notify import ...' muss das
# Verzeichnis darueber (der Paketordner) auf dem Pfad stehen.
sys.path.insert(0, os.path.dirname(os.path.dirname(_HERE)))

FAILS = []


def check(label, condition, detail=''):
    if condition:
        print(f'  [OK  ] {label}' + (f' - {detail}' if detail else ''))
    else:
        print(f'  [FAIL] {label}' + (f' - {detail}' if detail else ''))
        FAILS.append(label)


from notify import entry_data as ed  # noqa: E402

print('=== Hilfsfunktionen ===')
check('_unwrap packt {"value": ..} aus',
      ed._unwrap({'value': 42, 'unit': 'mg'}) == 42)
check('_unwrap laesst Zahlen in Ruhe', ed._unwrap(7) == 7)
flat = {}
ed._flatten({'entry': {'data': {'data': {'result_td5': 305.2,
                                         'sample': {'sample_name': 'X'}}}}}, '', flat)
check('_flatten findet Felder hinter den Envelope-Ebenen',
      flat.get('result_td5') == 305.2 and flat.get('sample.sample_name') == 'X',
      str(sorted(flat)))
check('_fmt formatiert mit Einheit', ed._fmt(305.234, '°C', 1) == '305.2 °C')

print()
print('=== Ergebnis- und Parameterdarstellung ===')
fields = {'result_td5': 305.234, 'result_td10': 330.5, 'result_residue': 30.17,
          'result_sample_mass_mg': 12.333, 'result_pan_type': 'Platinum HT',
          'result_pan_number': 3, 'result_sample_name': 'Kollidon VA64',
          'gas_atmosphere': 'Nitrogen', 'gas_flow_rate': 25.0,
          'balance_flow_rate': 10.0,
          'temperature_segments': [{'end_temp': 600.0, 'rate': 10.0},
                                   {'duration_min': 30.0}]}
res = ed.results(fields)
check('Td5 mit Einheit', res.get('td5') == '305.2 °C', str(res.get('td5')))
check('Mass loss aus dem Rueckstand gerechnet',
      res.get('mass_loss') == '69.8 %', str(res.get('mass_loss')))
check('Rueckstand', res.get('residue') == '30.2 %', str(res.get('residue')))
check('Tiegel mit Nummer', res.get('pan') == 'Platinum HT #3', str(res.get('pan')))
params = ed.parameters(fields)
check('Atmosphaere', params.get('atmosphere') == 'Nitrogen')
check('Gasmengen benannt', 'sample gas' in params.get('gas_flows', '')
      and 'balance gas' in params.get('gas_flows', ''), params.get('gas_flows'))
check('Segmente uebersetzt', params['segments'][0].get('end') == '600.0 °C'
      and params['segments'][1].get('hold') == '30.0 min', str(params['segments']))

print()
print('=== Kurvenauswahl ===')
sig = ed.signals({'result_temperature_signal': [25, 300, 400],
                  'result_dtg_signal': [0, -1, -6],
                  'result_dtg_cleaned_signal': [0, -1.1, -6.1],
                  'result_nonsense_signal': [1, 2, 3]})
check('nur die bekannten Kurven werden uebernommen',
      sorted(sig) == ['dtg', 'dtg_cleaned', 'temperature'], str(sorted(sig)))
check('leere Felder fallen raus', ed.signals({'result_dtg_signal': []}) == {})

print()
print('=== Echter Upload (wenn vorhanden) ===')
upload = sys.argv[1] if len(sys.argv) > 1 else ''
if not upload and os.path.isdir(ed.STAGING_ROOT):
    candidates = []
    for path in glob.glob(os.path.join(ed.STAGING_ROOT, '*', '*')):
        if glob.glob(os.path.join(path, 'archive', '*.msg')):
            candidates.append(path)
    if candidates:
        upload = os.path.basename(sorted(candidates, key=os.path.getmtime)[-1])
        upload = upload.split('-')[-1] if '-' in upload else upload

if not upload:
    print('  (kein Upload mit Archiv gefunden - uebersprungen)')
else:
    summary = ed.request_summary(upload)
    print(f'  Upload: {upload}')
    print(f'  Felder gelesen: {len(summary["fields"])}')
    print(f'  Sample: {summary["sample_name"]!r} | gemessen: {summary["measured"]}')
    print(f'  Ergebnisse: {summary["results"]}')
    print(f'  Parameter: {summary["parameters"]}')
    print(f'  Kurven: ' + ', '.join(f'{k}[{len(v)}]' for k, v in summary['signals'].items()))
    check('Archiv gelesen', bool(summary['fields']), f'{len(summary["fields"])} Felder')
    check('Ergebniswerte erkannt', bool(summary['sample_name']) and bool(summary['results']),
          f'{summary["sample_name"]!r} {summary["results"]}')
    check('Kurven vorhanden', bool(summary['signals']),
          ', '.join(f'{k}[{len(v)}]' for k, v in summary['signals'].items()))
    if summary['fields'].get('temperature_segments'):
        check('Programm erkannt', bool(summary['parameters']['segments']),
              str(summary['parameters']['segments']))
    else:
        print('  (Programm im Archiv nicht enthalten - Parameterpruefung uebersprungen)')

print()
print('ERGEBNIS:', 'ALLE CHECKS BESTANDEN' if not FAILS
      else f'{len(FAILS)} FEHLER: ' + '; '.join(FAILS))
sys.exit(1 if FAILS else 0)
