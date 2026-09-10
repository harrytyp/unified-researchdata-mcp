"""NOMAD-API-Zugriff für das TGA-Formular (serverseitig, hinter dem Oasis-Proxy).

Die App erbt die NOMAD-Session über das 'Authorization'-Cookie (Path=/nomad-oasis),
das die NOMAD-GUI nach dem Keycloak-Login setzt. Sie reicht den Token einfach an
die interne NOMAD-API weiter — die API validiert den JWT.
"""
from __future__ import annotations

import base64
import json
import os
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional

API_INTERNAL = os.environ.get(
    'NOMAD_API_INTERNAL', 'http://app:8000/nomad-oasis/api/v1')

# ── Units ────────────────────────────────────────────────────────────────────
# The form lets the user pick the unit they think in; NOMAD always stores the
# schema's canonical unit. NOMAD's own unit system accepts exactly these
# conversions for the TGA quantities (checked against nomad.units.ureg):
#   mass   -> milligram        (mg)
#   temp   -> degree_Celsius   (°C)
#   rate   -> delta_°C/minute  (a temperature *difference*, so K/min == °C/min)
#   time   -> minute           (min)
#   flow   -> milliliter/minute
# NOTE: never write "mL/min" in a NOMAD unit string - NOMAD's unit parser reads
# the "min" in "mL/min" as *milli-inch* (verified: ureg.parse_units('mL/min')
# -> milliliter / milliinch). Spell the unit out instead.
MASS_UNITS = {'mg': 1.0, 'g': 1000.0}
TIME_UNITS = {'min': 1.0, 's': 1.0 / 60.0, 'h': 60.0}
FLOW_UNITS = {'mL/min': 1.0, 'L/min': 1000.0}
TEMP_UNITS = ['°C', 'K']
RATE_UNITS = ['°C/min', 'K/min']


def to_canonical(kind: str, value, unit: str):
    """Convert a user-entered value into the schema's canonical unit.

    kind: 'mass' | 'temp' | 'rate' | 'time' | 'flow'
    Returns None for empty input (so optional fields stay unset).
    """
    if value in (None, ''):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if kind == 'mass':
        return v * MASS_UNITS.get(unit, 1.0)
    if kind == 'temp':
        # K -> °C (offset conversion); °C stays as-is
        return v - 273.15 if unit == 'K' else v
    if kind == 'rate':
        # heating rate is a temperature difference: K/min == °C/min
        return v
    if kind == 'time':
        return v * TIME_UNITS.get(unit, 1.0)
    if kind == 'flow':
        return v * FLOW_UNITS.get(unit, 1.0)
    return v


def from_canonical(kind: str, value, unit: str):
    """Inverse of to_canonical: show a canonical value in the user's unit.

    Used when the user switches a unit dropdown, so the number already typed
    is re-displayed in the new unit instead of silently changing meaning.
    """
    if value is None:
        return None
    v = float(value)
    if kind == 'mass':
        factor = MASS_UNITS.get(unit, 1.0)
        return v / factor if factor else v
    if kind == 'temp':
        return v + 273.15 if unit == 'K' else v
    if kind == 'rate':
        return v
    if kind == 'time':
        factor = TIME_UNITS.get(unit, 1.0)
        return v / factor if factor else v
    if kind == 'flow':
        factor = FLOW_UNITS.get(unit, 1.0)
        return v / factor if factor else v
    return v


def user_from_token(token: str) -> Optional[Dict[str, Any]]:
    """Decode the Keycloak JWT payload (name, username, sub) — no API call.

    token may be 'Bearer <jwt>' or plain '<jwt>'. Returns None if not a JWT.
    """
    jwt = (token or '').strip()
    if jwt.lower().startswith('bearer '):
        jwt = jwt[7:]
    if not jwt:
        return None
    try:
        payload = jwt.split('.')[1]
        payload += '=' * (-len(payload) % 4)
        d = json.loads(base64.urlsafe_b64decode(payload))
        if not isinstance(d, dict):
            return None
        return {
            'name': d.get('name') or d.get('preferred_username') or d.get('sub'),
            'username': d.get('preferred_username'),
            'sub': d.get('sub'),
            'email': d.get('email'),
        }
    except Exception:
        return None


def _api_raw(method: str, path: str, token: str, data: Optional[bytes] = None,
             headers: Optional[Dict[str, str]] = None, timeout: int = 180):
    # The NOMAD GUI cookie already carries "Bearer <jwt>"; a personal access
    # token passed in by a script usually does not. Accept both, otherwise the
    # API answers 401 'Authentication required.' for the bare form.
    auth = str(token)
    if not auth.lower().startswith('bearer '):
        auth = 'Bearer ' + auth
    h = {'Authorization': auth}
    h.update(headers or {})
    req = urllib.request.Request(API_INTERNAL + path, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def api_json(method: str, path: str, token: str, data: Any = None,
             timeout: int = 180):
    body = None
    hdrs = None
    if data is not None:
        body = data if isinstance(data, bytes) else json.dumps(data).encode()
        hdrs = {'Content-Type': 'application/json'}
    st, raw = _api_raw(method, path, token, body, hdrs, timeout)
    try:
        return st, json.loads(raw) if raw else {}
    except Exception:
        return st, {'raw': raw[:200].decode('utf-8', 'replace')}


def _multipart(fname: str, content: bytes):
    boundary = '----tgaform'
    body = b''
    body += ('--' + boundary + '\r\n').encode()
    body += (f'Content-Disposition: form-data; name="file"; filename="{fname}"\r\n').encode()
    body += b'Content-Type: application/octet-stream\r\n\r\n'
    body += content
    body += ('\r\n--' + boundary + '--\r\n').encode()
    return body, boundary


def create_tga_upload(token: str, archive: Dict[str, Any],
                      file_name: str,
                      display_name: Optional[str] = None
                      ) -> tuple[int, Optional[str], str]:
    """Create a NEW upload carrying a TgaMeasurement entry (process_now).

    file_name    : name of the uploaded .archive.json (becomes the mainfile).
    display_name : human readable upload name shown in the NOMAD GUI. Without
                   it NOMAD names the upload after the file (an unhelpful
                   '<sample>_<hex>.archive.json'), which made the request hard
                   to find in the GUI.

    Sends 'Accept: application/json' so NOMAD answers with JSON carrying the
    upload_id - instead of the plain-text thank-you page that forced the
    caller to poll the upload list for the newest matching name.

    Returns (http_status, upload_id | None, raw_body_text).
    """
    body, boundary = _multipart(file_name, json.dumps(archive).encode())
    path = '/uploads'
    if display_name:
        path += '?upload_name=' + urllib.parse.quote(str(display_name))
    st, raw = _api_raw(
        'POST', path, token, body,
        {'Content-Type': f'multipart/form-data; boundary={boundary}',
         'Accept': 'application/json'}, timeout=300)
    text = raw.decode('utf-8', 'replace')
    uid = None
    try:
        uid = (json.loads(text).get('data') or {}).get('upload_id')
    except Exception:
        uid = None
    return st, uid, text


def add_operator_group(token: str, upload_id: str, group_id: str) -> tuple[int, Any]:
    """Make the operator group a co-author of the upload.

    The upload is owned by the submitting user, so without this the TGA
    operator (a different account) could neither see the request nor write the
    result into it - unless it used a master/admin token. Adding the operator
    group as co-author keeps the submitter the owner (they keep seeing their
    upload) while letting any operator process it with their own account.

    Waits for the upload to be idle first: NOMAD rejects the metadata edit
    while a workflow is still running on the upload (it fails with
    "'NoneType' object has no attribute 'is_blocking'" because queue_blocked()
    looks at the currently running process flags).
    """
    wait_until_idle(token, upload_id)
    return api_json('POST', f'/uploads/{upload_id}/edit', token,
                    {'metadata': {'coauthor_groups': [group_id]}})


def find_newest_upload(token: str, name_prefix: str) -> Optional[str]:
    """Newest upload whose upload_name starts with name_prefix."""
    import time
    for _ in range(10):
        st, resp = api_json('GET', '/uploads?page_size=15&order=desc', token)
        data = resp.get('data', resp) if isinstance(resp, dict) else []
        if isinstance(data, dict):
            data = data.get('uploads', [])
        for u in (data if isinstance(data, list) else []):
            if str(u.get('upload_name', '')).startswith(name_prefix):
                return u.get('upload_id')
        time.sleep(2)
    return None


def upload_state(token: str, upload_id: str) -> Dict[str, Any]:
    st, resp = api_json('GET', f'/uploads/{upload_id}', token)
    data = resp.get('data', resp) if isinstance(resp, dict) else {}
    return data if isinstance(data, dict) else {}


def wait_until_idle(token: str, upload_id: str,
                    timeout: float = 300.0, poll: float = 2.0) -> bool:
    """Wait until the upload is not being processed.

    NOMAD rejects metadata edits (and extra process triggers) while a workflow
    is still running on the upload. Creating the upload starts such a workflow
    (the entry gets processed and the .tprc generated), so anything that edits
    upload metadata has to wait for it to settle first.
    Returns True if the upload became idle, False on timeout.
    """
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = upload_state(token, upload_id)
        if state and not state.get('process_running'):
            return True
        time.sleep(poll)
    return False


def _num(value) -> str:
    """Format a number for the method-name suggestion: 10.0 -> '10', 0.5 -> '0.5'."""
    try:
        return f'{float(value):g}'
    except (TypeError, ValueError):
        return str(value)


def suggest_method_name(segments, temp_unit: str = '°C', rate_unit: str = '°C/min',
                        time_unit: str = 'min', flow_unit: str = 'mL/min',
                        gas: str = None) -> str:
    """Build a readable method name from the entered segments.

    The method name is patched into the .tprc, where it becomes the procedure
    name the operator sees in TRIOS - so a name derived from the actual program
    ("Ramp 10 °C/min to 600 °C + Hold 30 min (N2)") is a far better default than
    an empty field or a fixed placeholder. The user can always overwrite it.
    """
    parts = []
    for seg in segments or []:
        if not isinstance(seg, dict):
            continue
        kind = seg.get('type')
        if kind == 'ramp':
            end_temp, rate = seg.get('end_temp'), seg.get('rate')
            if end_temp is not None and rate is not None:
                parts.append(f'Ramp {_num(rate)} {rate_unit} to '
                             f'{_num(end_temp)} {temp_unit}')
        elif kind == 'isothermal':
            duration = seg.get('duration_min')
            if duration is not None:
                parts.append(f'Hold {_num(duration)} {time_unit}')
        elif kind in ('mass_flow', 'balance_flow'):
            flow = seg.get('flow_rate')
            if flow is not None:
                label = 'Mass flow' if kind == 'mass_flow' else 'Balance flow'
                parts.append(f'{label} {_num(flow)} {flow_unit}')
    name = ' + '.join(parts)
    # Only mention the gas when there is an actual program to name - a fresh
    # form (no values entered yet) should suggest nothing at all.
    if gas and parts:
        name = f'{name} ({gas})'
    return name


def build_archive(form: Dict[str, Any]) -> Dict[str, Any]:
    """Map the form dict to a TgaMeasurement archive (matching the schema).

    Keys are the schema quantity names; segments are polymorphic with their
    concrete m_def. Mirrors the verified E2E payload structure.

    The user may enter values in the unit they think in (g instead of mg, K
    instead of °C, L/min, h, ...) - every value is converted into the unit the
    schema stores, so the NOMAD entry and the generated .tprc always carry
    canonical units. This mirrors how NOMAD's own ELN form behaves.
    """
    mass_unit = form.get('mass_unit') or 'mg'
    temp_unit = form.get('temp_unit') or '°C'
    rate_unit = form.get('rate_unit') or '°C/min'
    time_unit = form.get('time_unit') or 'min'
    flow_unit = form.get('flow_unit') or 'mL/min'

    segments = []
    for seg in form.get('segments') or []:
        seg_type = seg.get('type')
        mdef = {
            'ramp': 'instrument_data.schema.RampSegment',
            'isothermal': 'instrument_data.schema.IsothermalSegment',
            'mass_flow': 'instrument_data.schema.MassFlowSegment',
            'balance_flow': 'instrument_data.schema.BalanceFlowSegment',
        }.get(seg_type)
        if not mdef:
            continue
        item = {'m_def': mdef}
        if seg_type == 'ramp':
            end_temp = to_canonical('temp', seg.get('end_temp'), temp_unit)
            if end_temp is not None:
                item['end_temp'] = end_temp
            rate = to_canonical('rate', seg.get('rate'), rate_unit)
            if rate is not None:
                item['rate'] = rate
        elif seg_type == 'isothermal':
            duration = to_canonical('time', seg.get('duration_min'), time_unit)
            if duration is not None:
                item['duration_min'] = duration
        else:
            flow = to_canonical('flow', seg.get('flow_rate'), flow_unit)
            if flow is not None:
                item['flow_rate'] = flow
        segments.append(item)

    data: Dict[str, Any] = {
        'm_def': 'instrument_data.schema.TgaMeasurement',
        'process_now': True,
    }
    if form.get('procedure_name'):
        data['procedure_name'] = form['procedure_name']
    sample: Dict[str, Any] = {}
    if form.get('sample_name'):
        sample['sample_name'] = form['sample_name']
    mass = to_canonical('mass', form.get('sample_mass'), mass_unit)
    if mass is not None:
        sample['sample_mass'] = mass
        # the stored value is always in mg, so the unit field says so
        sample['sample_mass_unit'] = 'mg'
    if form.get('operator'):
        sample['operator'] = form['operator']
    if sample:
        data['sample'] = sample
    for key, kind in (('gas_flow_rate', 'flow'), ('balance_flow_rate', 'flow')):
        if form.get(key) not in (None, ''):
            value = to_canonical(kind, form.get(key), flow_unit)
            if value is not None:
                data[key] = value
    for key in ('crucible_type', 'pan_number', 'gas_atmosphere', 'comments'):
        if form.get(key) not in (None, ''):
            data[key] = form[key]
    if segments:
        data['temperature_segments'] = segments
    return {'data': data}
