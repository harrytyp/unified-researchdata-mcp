"""Local logic test for the TGA form's unit handling + archive building.

Pure-python (no NOMAD needed): nomad_api only uses the stdlib.
Run: python test_units.py
"""
import sys

import nomad_api as api

FAILS = []


def eq(label, got, want, tol=1e-9):
    try:
        ok = (got is None and want is None) or (
            got is not None and want is not None and abs(float(got) - float(want)) <= tol)
    except (TypeError, ValueError):
        ok = got == want
    if not ok:
        FAILS.append(label)
    print(f'  [{"OK " if ok else "FAIL"}] {label}: got={got!r} want={want!r}')


print('=== to_canonical ===')
eq('mass 0.005 g -> mg', api.to_canonical('mass', 0.005, 'g'), 5.0)
eq('mass 5 mg -> mg', api.to_canonical('mass', 5, 'mg'), 5.0)
eq('temp 773.15 K -> C', api.to_canonical('temp', 773.15, 'K'), 500.0)
eq('temp 500 C -> C', api.to_canonical('temp', 500, '°C'), 500.0)
eq('rate 10 K/min -> C/min', api.to_canonical('rate', 10, 'K/min'), 10.0)
eq('time 1 h -> min', api.to_canonical('time', 1, 'h'), 60.0)
eq('time 90 s -> min', api.to_canonical('time', 90, 's'), 1.5)
eq('flow 0.05 L/min -> mL/min', api.to_canonical('flow', 0.05, 'L/min'), 50.0)
eq('leer -> None', api.to_canonical('mass', '', 'g'), None)
eq('None -> None', api.to_canonical('mass', None, 'g'), None)

print('=== from_canonical (Roundtrip) ===')
for kind, unit, val in (('mass', 'g', 0.005), ('temp', 'K', 773.15),
                        ('rate', 'K/min', 10.0), ('time', 'h', 1.0),
                        ('time', 's', 90.0), ('flow', 'L/min', 0.05)):
    back = api.from_canonical(kind, api.to_canonical(kind, val, unit), unit)
    eq(f'roundtrip {kind} {val} {unit}', back, val, tol=1e-9)

print('=== build_archive: Einheiten landen kanonisch im Archiv ===')
form = {
    'sample_name': 'Probe A', 'sample_mass': 0.005, 'mass_unit': 'g',
    'operator': 'kolja', 'crucible_type': 'Alumina', 'pan_number': '3',
    'gas_atmosphere': 'N2', 'gas_flow_rate': 0.05, 'balance_flow_rate': 50,
    'flow_unit': 'L/min', 'procedure_name': 'TGA Analysis', 'comments': 'hi',
    'temp_unit': 'K', 'rate_unit': 'K/min', 'time_unit': 'min',
    'segments': [
        {'type': 'ramp', 'end_temp': 873.15, 'rate': 10.0},
        {'type': 'isothermal', 'duration_min': 30.0},
        {'type': 'mass_flow', 'flow_rate': 0.02},
        {'type': 'balance_flow', 'flow_rate': 0.01},
    ],
}
a = api.build_archive(form)['data']
s = a['sample']
eq('sample_mass in mg', s['sample_mass'], 5.0)
eq('sample_mass_unit', s.get('sample_mass_unit'), 'mg')
eq('gas_flow_rate in mL/min (0.05 L/min x1000 -> 50)', a['gas_flow_rate'], 50.0)
eq('balance_flow_rate in mL/min (50 L/min x1000)', a['balance_flow_rate'], 50000.0)
eq('ramp end_temp in C (873.15 K)', a['temperature_segments'][0]['end_temp'], 600.0)
eq('ramp rate', a['temperature_segments'][0]['rate'], 10.0)
eq('isothermal', a['temperature_segments'][1]['duration_min'], 30.0)
eq('mass_flow (0.02 L/min -> 20)', a['temperature_segments'][2]['flow_rate'], 20.0)
eq('balance_flow (0.01 L/min -> 10)', a['temperature_segments'][3]['flow_rate'], 10.0)
print('  segments m_def:',
      [x['m_def'].split('.')[-1] for x in a['temperature_segments']])
print('  process_now:', a.get('process_now'))

print('=== build_archive: Defaults (mg / C / mL/min) bleiben unveraendert ===')
form2 = {'sample_name': 'X', 'sample_mass': 5.0, 'mass_unit': 'mg',
         'gas_flow_rate': 50, 'flow_unit': 'mL/min', 'temp_unit': '°C',
         'rate_unit': '°C/min', 'time_unit': 'min',
         'segments': [{'type': 'ramp', 'end_temp': 600.0, 'rate': 10.0}]}
a2 = api.build_archive(form2)['data']
eq('mass unveraendert', a2['sample']['sample_mass'], 5.0)
eq('gas flow unveraendert', a2['gas_flow_rate'], 50.0)
eq('end_temp unveraendert', a2['temperature_segments'][0]['end_temp'], 600.0)

print()
print('ERGEBNIS:', 'ALLE TESTS BESTANDEN' if not FAILS else f'{len(FAILS)} FEHLER: {FAILS}')
sys.exit(1 if FAILS else 0)
