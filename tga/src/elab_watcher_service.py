"""
elab_watcher_service.py — v2: UX-aware status tracking.

Monitors elabFTW experiments and manages the measurement lifecycle.
"""
import os, sys, json, time, re, shutil, logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List

sys.path.insert(0, str(Path(__file__).parent))
from tprc_builder import build_tprc

import requests as req
import urllib3; urllib3.disable_warnings()

# ─── Configuration ──────────────────────────────────────────────
ELAB_URL = "https://elntest.ub.tum.de/api/v2"
ELAB_KEY = open("/app/plugins/elab_key.txt").read().strip()
TEAM_ID = 29
POLL_INTERVAL = 30
TPRC_DIR = Path("/app/plugins/tprc")
TPRC_DIR.mkdir(parents=True, exist_ok=True)


def _headers():
    return {'Authorization': ELAB_KEY}


def _get(path):
    r = req.get(f"{ELAB_URL}{path}", headers=_headers(), verify=False, timeout=15)
    return r.json() if r.status_code == 200 else None


def _patch(id_or_path, data):
    path = f"/experiments/{id_or_path}" if isinstance(id_or_path, int) else id_or_path
    r = req.patch(f"{ELAB_URL}{path}", json=data,
                 headers={**_headers(), 'Content-Type': 'application/json'},
                 verify=False, timeout=15)
    return r.status_code in (200, 201)


def set_status(eid: int, status: str):
    """Update the measurement_status extra_field on an experiment."""
    exp = _get(f"/experiments/{eid}")
    if not exp:
        return False
    raw = exp.get('metadata', '')
    if isinstance(raw, str):
        try:
            meta = json.loads(raw) if raw else {}
        except:
            meta = {}
    elif isinstance(raw, dict):
        meta = raw
    else:
        meta = {}
    ef = meta.get('extra_fields', {}) if isinstance(meta, dict) else {}
    if isinstance(ef, dict):
        ef['measurement_status'] = {'type': 'select', 'title': 'Measurement Status', 'value': status}
    meta['extra_fields'] = ef
    return _patch(eid, {'metadata': json.dumps(meta)})


def get_extra_fields(exp: Dict) -> Dict:
    raw = exp.get('metadata', '')
    if isinstance(raw, str):
        try:
            meta = json.loads(raw) if raw else {}
        except:
            meta = {}
    elif isinstance(raw, dict):
        meta = raw
    else:
        meta = {}
    ef = meta.get('extra_fields', {}) if isinstance(meta, dict) else {}
    result = {}
    for k, v in ef.items():
        if isinstance(v, dict):
            val = v.get("value") or v.get("default") or ""
            if not val:
                continue
            result[k] = val
        elif v:
            result[k] = v
    return result


def run_watcher(once=False):
    log = logging.getLogger("elab_watcher")
    logging.basicConfig(level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s')
    
    log.info(f"Watching elabFTW team {TEAM_ID} for experiments...")
    
    while True:
        try:
            data = _get(f"/experiments?team={TEAM_ID}&limit=50")
            exps = data if isinstance(data, list) else []
            log.info(f"Found {len(exps)} experiments")
            
            for exp in exps:
                eid = exp.get('id', 0)
                fields = get_extra_fields(exp)
                meas_status = fields.get('measurement_status', '')
                sample_name = fields.get('sample_name', '')
                
                # ─── Status: "Ready" → Generate .tprc (read-only check) ───
                local_tprc = TPRC_DIR / f"exp{eid}.tprc"
                has_local = local_tprc.exists()
                
                if meas_status == "Ready" and sample_name and not has_local:
                    log.info(f"[{eid}] Status=Ready, generating .tprc for {sample_name}")
                    params = {
                        'sample_name': sample_name,
                        'procedure_name': fields.get('procedure_name', f"TGA_{sample_name}"),
                        'heating_rate': float(fields.get('heating_rate', 10)),
                        'temperature_end': float(fields.get('temperature_end', 400)),
                        'gas_atmosphere': fields.get('gas_atmosphere', 'Nitrogen'),
                    }
                    try:
                        tprc_bytes = build_tprc(params)
                        tprc_path = TPRC_DIR / f"exp{eid}.tprc"
                        tprc_path.write_bytes(tprc_bytes)
                        log.info(f"  → Generated .tprc ({len(tprc_bytes)} bytes)")
                        # ─── Upload .tprc to NOMAD (authenticated) ───
                        try:
                            PAT = open("/app/plugins/.nomad_pat").read().strip()
                            NOMAD_URL = "http://app:8000/nomad-oasis"
                            with open(tprc_path, "rb") as f:
                                nr = req.post(
                                    f"{NOMAD_URL}/api/v1/uploads",
                                    files={"file": (f"exp{eid}.tprc", f, "application/octet-stream")},
                                    headers={"Authorization": f"Bearer {PAT}"},
                                    verify=False, timeout=60
                                )
                            if nr.status_code == 200:
                                log.info(f"  → Uploaded to NOMAD (exp{eid}.tprc)")
                            else:
                                log.warning(f"  → NOMAD upload: HTTP {nr.status_code}")
                        except Exception as nomad_err:
                            log.warning(f"  → NOMAD upload error: {nomad_err}")
                    except Exception as e:
                        log.error(f"  → Error: {e}")
                
                # ─── Status reset: "Draft" → delete .tprc ───
                if meas_status == "Draft" and has_local:
                    local_tprc.unlink(missing_ok=True)
                    log.info(f"[{eid}] Status=Draft, deleted local .tprc")
                
                # ─── Check for .tri uploads ───
                if has_local and meas_status in ("Ready", "Running"):
                    uploads_r = req.get(f"{ELAB_URL}/experiments/{eid}/uploads",
                                       headers=_headers(), verify=False, timeout=15)
                    if uploads_r.status_code == 200:
                        uploads = uploads_r.json()
                        for u in uploads:
                            if not isinstance(u, dict):
                                continue
                            fname = u.get('real_name', '') or u.get('filename', '')
                            if not fname.lower().endswith('.tri'):
                                continue
                            # Download .tri
                            fid = u.get('id', u.get('upload_id', ''))
                            dl = req.get(f"{ELAB_URL}/experiments/{eid}/uploads/{fid}",
                                        headers=_headers(), verify=False, timeout=30)
                            if dl.status_code != 200:
                                continue
                            tri_path = TPRC_DIR / f"exp{eid}.tri"
                            tri_path.write_bytes(dl.content)
                            log.info(f"[{eid}] Downloaded .tri ({len(dl.content)} bytes)")
                            
                            # Parse and upload to NOMAD
                            try:
                                from e2e_tga_service import parse_tri_file, upload_to_nomad
                                parsed = parse_tri_file(str(tri_path))
                                sn = parsed.get('metadata', {}).get('samplename', '?')
                                log.info(f"  → Parsed: {sn}, signals: {list(parsed.get('signals', {}).keys())}")
                                
                                ok, result = upload_to_nomad(str(tri_path))
                                if ok:
                                    log.info(f"  → NOMAD upload OK")
                                else:
                                    log.warning(f"  → NOMAD upload: {result[:100]}")
                                
                                # Clean up
                                tri_path.unlink(missing_ok=True)
                            except Exception as pe:
                                log.error(f"  → Processing error: {pe}")
        
        except Exception as e:
            log.error(f"Watcher error: {e}")
        
        if once:
            break
        time.sleep(POLL_INTERVAL)


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--once', action='store_true')
    args = ap.parse_args()
    run_watcher(once=args.once)
