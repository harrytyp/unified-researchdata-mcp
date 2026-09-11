"""Unit test for the TRIOS JSON metadata extraction (header path).

The server always reads exports through the STREAMING reader, whose metadata
comes from _meta_from_header() - so this is the function that decides whether
crucible + weighed mass reach NOMAD at all.

Run: python test_trios_meta.py
"""
import sys

from trios_json_reader import _meta_from_header, extract_trios_signals

FAILS = []


def check(label, cond, detail=''):
    if not cond:
        FAILS.append(label)
    print(f'  [{"OK  " if cond else "FAIL"}] {label}{(" - " + str(detail)) if detail else ""}')


# The real export layout: pretty-printed, CRLF, mass nested one level deeper
HEADER = (
    '{\r\n'
    '  "Schema": {\r\n'
    '    "Url": "https://software.tainstruments.com/schemas/TRIOSJSONExportSchema"\r\n'
    '  },\r\n'
    '  "Operators": [\r\n'
    '    {\r\n'
    '      "Name": "PB"\r\n'
    '    }\r\n'
    '  ],\r\n'
    '  "Sample": {\r\n'
    '    "Name": "Kollidon VA64",\r\n'
    '    "PanNumber": 1,\r\n'
    '    "PanType": "Platinum HT",\r\n'
    '    "Mass": {\r\n'
    '      "Value": 12.333204134806891,\r\n'
    '      "Unit": {\r\n'
    '        "Name": "mg"\r\n'
    '      }\r\n'
    '    }\r\n'
    '  },\r\n'
    '  "Procedure": {\r\n'
    '    "Name": "LBAM Hofmann 10 Kmin 400 C N2",\r\n'
    '    "Steps": []\r\n'
    '  },\r\n'
    '  "Results": {"Processed": {}}\r\n'
    '}\r\n'
)

print('=== Echter Export-Header (pretty-printed, Masse verschachtelt) ===')
m = _meta_from_header(HEADER)
for key, want in (('sample_name', 'Kollidon VA64'),
                  ('pan_type', 'Platinum HT'),
                  ('pan_number', '1'),
                  ('operator', 'PB'),
                  ('procedure_name', 'LBAM Hofmann 10 Kmin 400 C N2')):
    check(f'{key} = {want!r}', m.get(key) == want, m.get(key))
check('sample_mass_mg = 12.333204134806891',
      abs((m.get('sample_mass_mg') or 0) - 12.333204134806891) < 1e-12,
      m.get('sample_mass_mg'))

print()
print('=== Varianten / Robustheit ===')
compact = ('{"Sample":{"Name":"S1","PanNumber":"7","PanType":"Alumina",'
           '"Mass":{"Value":5.5,"Unit":{"Name":"mg"}}}}')
m2 = _meta_from_header(compact)
check('kompaktes JSON: pan_number als String', m2.get('pan_number') == '7', m2.get('pan_number'))
check('kompaktes JSON: Masse', m2.get('sample_mass_mg') == 5.5, m2.get('sample_mass_mg'))
check('kompaktes JSON: pan_type', m2.get('pan_type') == 'Alumina', m2.get('pan_type'))

g_unit = ('{"Sample":{"Name":"S2","Mass":{"Value":0.0125,"Unit":{"Name":"g"}}}}')
m3 = _meta_from_header(g_unit)
check('Masse in g wird in mg umgerechnet (0.0125 g -> 12.5 mg)',
      abs((m3.get('sample_mass_mg') or 0) - 12.5) < 1e-9, m3.get('sample_mass_mg'))

no_pan = '{"Sample":{"Name":"S3","Mass":{"Value":9.0,"Unit":{"Name":"mg"}}}}'
m4 = _meta_from_header(no_pan)
check('fehlender Tiegel -> None (kein Absturz)',
      m4.get('pan_type') is None and m4.get('pan_number') is None, m4.get('pan_type'))
check('Masse trotzdem gelesen', m4.get('sample_mass_mg') == 9.0, m4.get('sample_mass_mg'))

empty = '{}'
m5 = _meta_from_header(empty)
check('leerer Header -> alle Felder None',
      all(m5.get(k) is None for k in ('sample_name', 'pan_type', 'pan_number',
                                      'sample_mass_mg', 'operator', 'procedure_name')),
      m5)

# "Name" occurs twice inside Sample (sample name + unit name) - the sample
# name must not be taken from the unit block
order = ('{"Sample":{"PanType":"Platinum","Mass":{"Value":1.0,'
         '"Unit":{"Name":"mg"}},"Name":"AfterMass"}}')
m6 = _meta_from_header(order)
check('Sample-Name wird nicht mit dem Einheiten-Namen verwechselt',
      m6.get('sample_name') == 'AfterMass', m6.get('sample_name'))

print()
print('=== extract_trios_signals (Voll-Parse-Pfad) liefert dieselben Felder ===')
# minimal but structurally valid export: Results.Processed needs Rows + a
# column header that classifies as a signal
data = {
    'Sample': {'Name': 'Kollidon VA64', 'PanNumber': 1, 'PanType': 'Platinum HT',
               'Mass': {'Value': 12.333204134806891, 'Unit': {'Name': 'mg'}}},
    'Operators': [{'Name': 'PB'}],
    'Procedure': {'Name': 'LBAM', 'Steps': []},
    'Results': {'Processed': {
        'ColumnHeaders': {'Temperatur_°C': {}, 'Masse_%': {}, 'Zeit_min': {}},
        'Rows': [
            {'Temperatur_°C': 25.0, 'Masse_%': 100.0, 'Zeit_min': 0.0},
            {'Temperatur_°C': 300.0, 'Masse_%': 95.0, 'Zeit_min': 27.5},
            {'Temperatur_°C': 600.0, 'Masse_%': 30.0, 'Zeit_min': 57.5},
        ],
    }},
    'StartTime': '2026-09-09 10:00:00',
}
res = extract_trios_signals(data)
meta = res['meta']
check('pan_type', meta.get('pan_type') == 'Platinum HT', meta.get('pan_type'))
check('pan_number', str(meta.get('pan_number')) == '1', meta.get('pan_number'))
check('sample_mass_mg', meta.get('sample_mass_mg') == 12.333204134806891,
      meta.get('sample_mass_mg'))
check('sample_name', meta.get('sample_name') == 'Kollidon VA64', meta.get('sample_name'))
check('Signale weiterhin extrahiert', len(res['signals'].get('temperature') or []) == 3,
      res['signals'].get('temperature'))

print()
print('ERGEBNIS:', 'ALLE TESTS BESTANDEN' if not FAILS else f'{len(FAILS)} FEHLER: {FAILS}')
sys.exit(1 if FAILS else 0)
