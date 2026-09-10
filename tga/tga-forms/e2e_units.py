"""E2E test for the TGA request form: units + who can see the upload.

Verifies, against the real NOMAD Oasis API:

  1. UNITS   - the form's build_archive() converts the values the user typed in
               the unit they picked (g, K, L/min, h) into the schema's
               canonical units (mg, °C, mL/min, min) BEFORE the upload.
  2. VISIBILITY - the request is created by a NON-ADMIN user account, the
               operator group is added as co-author, and the submitting user
               keeps seeing the request, the entry and the result files.
  3. OPERATOR  - if TGA_E2E_OPERATOR_USER is set to a non-admin NOMAD user that
               is a member of TGA_OPERATOR_GROUP, this also checks that this
               operator can see the request (which it could NOT before the
               group was added) and write the result into it.

Run inside the nomad_oasis_app container:

    docker exec nomad_oasis_app python3 /tmp/e2e_units.py

Needs the form's nomad_api.py next to it (/tmp/nomad_api.py) and NOMAD_PAT in
the container environment.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

sys.path.insert(0, '/tmp')
import nomad_api as api  # the form's module

API = 'http://localhost:8000/nomad-oasis/api/v1'
api.API_INTERNAL = API

TGA_OPERATOR_GROUP = os.environ.get(
    'TGA_OPERATOR_GROUP', 'tga-operators-6a7ae5e4cec5e87bf39df8a3')
# a plain (non-admin) NOMAD user used as the 'submitter'
TGA_E2E_USER = os.environ.get('TGA_E2E_USER',
                              '500a3642-1524-4205-9d0d-b750e3d780da')
# a non-admin user that IS a member of the operator group (optional)
TGA_E2E_OPERATOR_USER = os.environ.get('TGA_E2E_OPERATOR_USER', '')
ADMIN_PAT = 'Bearer ' + os.environ['NOMAD_PAT']
FAILS = []

from nomad.auth.tokens import generate_simple_token  # noqa: E402


def call(method, path, token, data=None, headers=None, timeout=180):
    h = {'Authorization': token}
    h.update(headers or {})
    req = urllib.request.Request(API + path, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def jget(path, token):
    st, raw = call('GET', path, token)
    try:
        return st, json.loads(raw or b'{}')
    except Exception:
        return st, {}


def check(label, cond, detail=''):
    if not cond:
        FAILS.append(label)
    print(f'  [{"OK  " if cond else "FAIL"}] {label}{(" - " + str(detail)) if detail else ""}')


tok_sub = 'Bearer ' + generate_simple_token(TGA_E2E_USER, 3600)
tok_op = ('Bearer ' + generate_simple_token(TGA_E2E_OPERATOR_USER, 3600)
          if TGA_E2E_OPERATOR_USER else None)

# ── 1. units ────────────────────────────────────────────────────────────────
print('1) Einheiten: Formulareingabe -> kanonische Einheiten im Archiv')
form = {
    'sample_name': 'E2E-UNITS', 'sample_mass': 5.0, 'mass_unit': 'mg',
    'operator': 'E2E', 'crucible_type': 'Alumina', 'pan_number': '7',
    'gas_atmosphere': 'N2', 'gas_flow_rate': 0.06, 'balance_flow_rate': 20,
    'flow_unit': 'L/min', 'procedure_name': 'E2E Units',
    'temp_unit': 'K', 'rate_unit': 'K/min', 'time_unit': 'h',
    'segments': [
        {'type': 'ramp', 'end_temp': 873.15, 'rate': 10.0},   # 600 °C
        {'type': 'isothermal', 'duration_min': 0.5},          # 30 min
        {'type': 'mass_flow', 'flow_rate': 0.05},             # 50 mL/min
    ],
}
data = api.build_archive(form)['data']
check('sample_mass 5 mg bleibt 5', data['sample']['sample_mass'] == 5.0)
check('sample_mass_unit = mg', data['sample'].get('sample_mass_unit') == 'mg')
check('gas flow 0.06 L/min -> 60 mL/min', data['gas_flow_rate'] == 60.0,
      data.get('gas_flow_rate'))
check('balance flow 20 L/min -> 20000 mL/min', data['balance_flow_rate'] == 20000.0)
check('end_temp 873.15 K -> 600 °C',
      abs(data['temperature_segments'][0]['end_temp'] - 600.0) < 1e-6)
check('hold 0.5 h -> 30 min', data['temperature_segments'][1]['duration_min'] == 30.0)
check('seg flow 0.05 L/min -> 50 mL/min',
      data['temperature_segments'][2]['flow_rate'] == 50.0)

# ── 2. upload as a non-admin submitter ──────────────────────────────────────
print()
print('2) Upload als Nicht-Admin-Submitter (Sichtbarkeit)')
sample = 'E2E-UNITS-' + uuid.uuid4().hex[:6]
data['sample']['sample_name'] = sample
display = f'TGA Request: {sample} (E2E)'
st, uid, body = api.create_tga_upload(tok_sub, {'data': data},
                                      f'{sample}.archive.json', display)
check('Upload erstellt', st in (200, 201), f'HTTP {st} {body[:80]}')
check('upload_id direkt zurueckgegeben', bool(uid), uid)
if not uid:
    print('ohne upload_id nicht fortsetzbar')
    sys.exit(1)

st, resp = jget(f'/uploads/{uid}', tok_sub)
up = resp.get('data') or {}
check('lesbarer upload_name', up.get('upload_name') == display, up.get('upload_name'))
check('main_author = Submitter (bleibt Eigentuemer)',
      up.get('main_author') == TGA_E2E_USER, up.get('main_author'))

if tok_op:
    st_op_before, _ = call('GET', f'/uploads/{uid}', tok_op)
    check('Operator sieht den Request VOR der Gruppe nicht',
          st_op_before in (401, 403), f'HTTP {st_op_before}')

nomad_api = api  # module alias used below for readability
api.wait_until_idle(tok_sub, uid)
gst, gres = api.add_operator_group(tok_sub, uid, TGA_OPERATOR_GROUP)
check('Operator-Gruppe als Co-Author gesetzt', gst in (200, 201),
      f'HTTP {gst} {str(gres)[:100]}')
st, resp = jget(f'/uploads/{uid}', tok_sub)
check('coauthor_groups enthaelt die Operator-Gruppe',
      TGA_OPERATOR_GROUP in (resp.get('data', {}).get('coauthor_groups') or []),
      resp.get('data', {}).get('coauthor_groups'))

if tok_op:
    st_op_after, _ = call('GET', f'/uploads/{uid}', tok_op)
    check('Operator (Gruppenmitglied) sieht den Request NACH der Gruppe',
          st_op_after == 200, f'HTTP {st_op_after}')
    res = json.dumps({'Sample': {'Name': sample}}).encode()
    st, raw = call('PUT', f'/uploads/{uid}/raw/?file_name={sample}.json', tok_op,
                   res, {'Content-Type': 'application/octet-stream'})
    check('Operator schreibt das Ergebnis in den Request-Upload', st in (200, 201),
          f'HTTP {st}')

time.sleep(6)
st, raw = call('GET', f'/uploads/{uid}/rawdir/', tok_sub)
check('Submitter sieht den .tprc', b'.tprc' in raw, raw[:160])
check('Submitter sieht den Eintrag', b'.archive.json' in raw)

# ── 3. entry values in the archive ─────────────────────────────────────────
print()
print('3) Eintrag im Archiv (Prozess-Ergebnis)')
for _ in range(12):
    st, resp = jget(f'/uploads/{uid}/entries', tok_sub)
    if (resp.get('data') or []):
        break
    time.sleep(3)
entries = resp.get('data') or []
check('Eintrag wurde erzeugt', len(entries) > 0, len(entries))
if entries:
    eid = entries[0].get('entry_id')
    st, d = jget(f'/uploads/{uid}', ADMIN_PAT)
    check('process_status = SUCCESS',
          (d.get('data') or {}).get('process_status') == 'SUCCESS',
          (d.get('data') or {}).get('process_status'))
    st, d = jget(f'/uploads/{uid}/archive/{eid}', ADMIN_PAT)
    # GET /uploads/{uid}/archive/{eid} -> {"data": {"archive": {"data": {...}}}}
    inner = ((d.get('data') or {}).get('archive') or {}).get('data') or {}
    sm = (inner.get('sample') or {})
    check('Archiv: sample_mass = 5 mg', sm.get('sample_mass') == 5.0, sm.get('sample_mass'))
    segs = inner.get('temperature_segments') or [{}]
    check('Archiv: end_temp = 600 °C (aus 873.15 K)',
          abs(float(segs[0].get('end_temp') or 0) - 600.0) < 1e-6, segs[0].get('end_temp'))
    check('Archiv: gas_flow_rate = 60 mL/min (aus 0.06 L/min)',
          inner.get('gas_flow_rate') == 60.0, inner.get('gas_flow_rate'))

st, _ = call('DELETE', f'/uploads/{uid}', ADMIN_PAT)
print('cleanup HTTP', st)
print()
print('ERGEBNIS:', 'ALLE CHECKS BESTANDEN' if not FAILS else f'{len(FAILS)} FEHLER: {FAILS}')
sys.exit(1 if FAILS else 0)
