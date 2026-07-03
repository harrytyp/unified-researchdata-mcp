"""
elab_watcher_service.py — Server-side elabFTW watcher.

Monitors elabFTW for TGA experiments:
  1. Detects new experiments with status "Running" / trigger value
  2. Generates .tprc from extra_fields → attaches to entry
  3. Monitors for .tri file attachments
  4. Processes .tri → NOMAD → pushes results to elabFTW body

Runs as a daemon on the NOMAD server.
"""
import os, sys, json, time, re, logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List

sys.path.insert(0, str(Path(__file__).parent))
from tprc_builder import build_tprc, parse_tprc
from e2e_tga_service import parse_tri_file, upload_to_nomad, push_to_elabftw

import requests as req
import urllib3; urllib3.disable_warnings()


# ─── Configuration ──────────────────────────────────────────────
ELAB_URL = "https://elntest.ub.tum.de/api/v2"
ELAB_KEY = open("/app/plugins/elab_key.txt").read().strip()
TEAM_ID = 29
CATEGORY_ID = 5  # TGA category
TRIGGER_FIELD = "status"  # Could be extra_field or item status
TRIGGER_VALUE = "Running"
POLL_INTERVAL = 30  # seconds
MAX_RETRY = 60  # max 30 min wait for NOMAD processing

WATCHER_DIR = Path("/app/.volumes/watcher")
PROCESSED_FILE = WATCHER_DIR / ".elab_processed.json"


def _headers():
    return {'Authorization': ELAB_KEY}


def _get(path):
    r = req.get(f"{ELAB_URL}{path}", headers=_headers(), verify=False, timeout=15)
    return r.json() if r.status_code == 200 else None


def _patch(path, data):
    r = req.patch(f"{ELAB_URL}{path}", json=data,
                 headers={**_headers(), 'Content-Type': 'application/json'},
                 verify=False, timeout=15)
    return r.status_code in (200, 201)


def _upload_file(item_id, filepath):
    with open(filepath, 'rb') as f:
        r = req.post(f"{ELAB_URL}/experiments/{item_id}/uploads",
                    files={'file': (Path(filepath).name, f, 'application/octet-stream')},
                    headers=_headers(), verify=False, timeout=60)
    return r.status_code in (200, 201)


def _get_uploads(item_id):
    r = req.get(f"{ELAB_URL}/experiments/{item_id}/uploads", headers=_headers(), verify=False, timeout=15)
    return r.json() if r.status_code == 200 else []


def _download_upload(item_id, upload):
    if not isinstance(upload, dict):
        return None, None
    uid = upload.get('id', upload.get('upload_id', ''))
    name = upload.get('real_name', upload.get('filename', ''))
    if not uid or not name:
        return None, None
    
    r = req.get(f"{ELAB_URL}/experiments/{item_id}/uploads/{uid}",
               headers=_headers(), verify=False, timeout=30)
    if r.status_code == 200:
        return name, r.content
    return None, None


def get_experiments() -> List[Dict]:
    """Fetch recent TGA experiments."""
    data = _get(f"/experiments?team={TEAM_ID}&limit=30")
    return data if isinstance(data, list) else []


def get_extra_fields(exp: Dict) -> Dict:
    raw = exp.get('metadata', '{}')
    if isinstance(raw, str):
        try:
            meta = json.loads(raw) if raw else {}
        except:
            meta = {}
    elif isinstance(raw, dict):
        meta = raw
    else:
        meta = {}
    ef = meta.get('extra_fields', {})
    # Flatten: values are nested in {type, title, value} dicts
    result = {}
    for k, v in ef.items():
        if isinstance(v, dict):
            result[k] = v.get("value", v.get("title", ""))
        else:
            result[k] = v
    return result


def is_triggered(exp: Dict) -> bool:
    """Check if experiment status matches trigger."""
    # Check status_title (human-readable, e.g. "Running")
    st = exp.get('status_title', '') or ''
    if isinstance(st, str) and st.lower() == TRIGGER_VALUE.lower():
        return True
    # Check timestamped status (numeric 122 = Running)
    return False


def run_watcher(once=False):
    """Main watcher loop."""
    log = logging.getLogger("elab_watcher")
    logging.basicConfig(level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s')
    
    WATCHER_DIR.mkdir(parents=True, exist_ok=True)
    
    processed = {}
    if PROCESSED_FILE.exists():
        processed = json.loads(PROCESSED_FILE.read_text())
    
    log.info(f"Watching elabFTW team {TEAM_ID} for TGA entries...")
    
    while True:
        try:
            exps = get_experiments()
            log.info(f"Found {len(exps)} experiments")
            
            for exp in exps:
                eid = exp.get('id', 0)
                if str(eid) in processed:
                    continue
                
                title = exp.get('title', '') or ''
                fields = get_extra_fields(exp)
                
                # Step 1: Check if we need to generate .tprc
                uploads = _get_uploads(eid)
                has_tprc = any(
                    isinstance(u, dict) and 
                    (u.get('real_name', '') or u.get('filename', '')).endswith('.tprc')
                    for u in uploads
                )
                
                sample_name = ''
                if isinstance(fields, dict):
                    sample_name = fields.get('sample_name', '') or ''
                
                if not has_tprc and sample_name and is_triggered(exp):
                    log.info(f"[{eid}] Generating .tprc for {sample_name}")
                    
                    # Build .tprc from extra_fields
                    params = {
                        'sample_name': sample_name,
                        'procedure_name': fields.get('procedure_name', f"TGA_{sample_name}"),
                        'heating_rate': float(fields.get('heating_rate', 10)),
                        'temperature_end': float(fields.get('temperature_end', 400)),
                        'gas_atmosphere': fields.get('gas_atmosphere', 'Nitrogen'),
                    }
                    
                    try:
                        tprc_bytes = build_tprc(params)
                        tprc_name = f"item{eid}_{sample_name.replace(' ', '_')}.tprc"
                        tprc_path = WATCHER_DIR / tprc_name
                        tprc_path.write_bytes(tprc_bytes)
                        
                        # Attach to elabFTW
                        if _upload_file(eid, str(tprc_path)):
                            log.info(f"  → Attached .tprc to item {eid}")
                        else:
                            log.error(f"  → Failed to attach .tprc")
                    except Exception as e:
                        log.error(f"  → .tprc error: {e}")
                
                # Step 2: Check for new .tri uploads
                tri_uploads = [
                    u for u in uploads 
                    if isinstance(u, dict) and 
                    (u.get('real_name', '') or u.get('filename', '')).lower().endswith('.tri')
                ]
                
                if tri_uploads and str(eid) not in processed:
                    for tri_u in tri_uploads:
                        log.info(f"[{eid}] Processing .tri upload...")
                        
                        # Download .tri
                        name, data = _download_upload(eid, tri_u)
                        if not data:
                            log.error(f"  → Download failed")
                            continue
                        
                        # Save locally
                        local_tri = WATCHER_DIR / f"item{eid}_{name}"
                        local_tri.write_bytes(data)
                        log.info(f"  → Downloaded {name} ({len(data)} bytes)")
                        
                        try:
                            # Parse
                            parsed = parse_tri_file(str(local_tri))
                            m = parsed.get('metadata', {})
                            log.info(f"  → Parsed: {m.get('samplename', '?')}")
                            
                            # Upload to NOMAD
                            ok, result = upload_to_nomad(str(local_tri))
                            if ok:
                                log.info(f"  → NOMAD upload OK: {result[:50]}")
                            else:
                                log.warning(f"  → NOMAD upload: {result[:100]}")
                                # Still push to elabFTW without NOMAD link
                            
                            # Push to elabFTW body
                            ok2 = push_to_elabftw(eid, parsed, result if ok else "local")
                            if ok2[0]:
                                log.info(f"  → elabFTW body updated ✓")
                                processed[str(eid)] = {
                                    'time': datetime.now().isoformat(),
                                    'status': 'completed',
                                }
                            else:
                                log.error(f"  → elabFTW push failed")
                            
                            PROCESSED_FILE.write_text(json.dumps(processed, indent=2))
                            
                        except Exception as e:
                            log.error(f"  → Processing error: {e}")
                            processed[str(eid)] = {
                                'time': datetime.now().isoformat(),
                                'status': f'error: {str(e)[:50]}',
                            }
                            PROCESSED_FILE.write_text(json.dumps(processed, indent=2))
        
        except Exception as e:
            log.error(f"Watcher error: {e}")
        
        if once:
            break
        
        time.sleep(POLL_INTERVAL)


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--once', action='store_true', help='Run once and exit')
    args = ap.parse_args()
    
    if args.once:
        run_watcher(once=True)
    else:
        run_watcher(once=False)
