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
    h = {'Authorization': token}
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
                      upload_name: str) -> tuple[int, str]:
    """Create a NEW upload carrying a TgaMeasurement entry (process_now).

    POST /uploads answers with an HTML thank-you page (not JSON); the upload
    is created server-side regardless. Returns (http_status, raw_body).
    """
    body, boundary = _multipart(upload_name, json.dumps(archive).encode())
    st, raw = _api_raw(
        'POST', '/uploads', token, body,
        {'Content-Type': f'multipart/form-data; boundary={boundary}'}, timeout=300)
    return st, raw.decode('utf-8', 'replace')


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


def build_archive(form: Dict[str, Any]) -> Dict[str, Any]:
    """Map the form dict to a TgaMeasurement archive (matching the schema).

    Keys are the schema quantity names; segments are polymorphic with their
    concrete m_def. Mirrors the verified E2E payload structure.
    """
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
            if seg.get('end_temp') is not None:
                item['end_temp'] = seg['end_temp']
            if seg.get('rate') is not None:
                item['rate'] = seg['rate']
        elif seg_type == 'isothermal':
            if seg.get('duration_min') is not None:
                item['duration_min'] = seg['duration_min']
        else:
            if seg.get('flow_rate') is not None:
                item['flow_rate'] = seg['flow_rate']
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
    if form.get('sample_mass') is not None:
        sample['sample_mass'] = form['sample_mass']
    if form.get('operator'):
        sample['operator'] = form['operator']
    if sample:
        data['sample'] = sample
    for key in ('crucible_type', 'pan_number', 'gas_atmosphere',
                'gas_flow_rate', 'balance_flow_rate', 'comments'):
        if form.get(key) not in (None, ''):
            data[key] = form[key]
    if segments:
        data['temperature_segments'] = segments
    return {'data': data}
