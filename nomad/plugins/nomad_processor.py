#!/usr/bin/env python3
"""
NOMAD TGA Processor — polls NOMAD API for new TGA uploads, processes them,
and pushes results to elabFTW. Runs inside the NOMAD container.

This replaces the local-watch-folder approach: the Windows uploader sends raw
files to NOMAD, this script picks them up, parses/computes, and pushes to elabFTW.

Usage:
    python nomad_processor.py watch                   # poll continuously
    python nomad_processor.py process <upload_id>     # one-shot

Environment:
    NOMAD_API_URL       default: http://localhost:8000/api/v1
    NOMAD_PAT           Personal Access Token
    ELABFTW_API_URL     elabFTW API base URL
    ELABFTW_API_KEY     elabFTW API key
    ELABFTW_TEAM        Team ID (default: 29)
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add plugins to path
_plugin_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(_plugin_dir))

from instrument_data.parser import parse_file, detect_format, extract_tga_metadata
from instrument_data.elabftw_client import ElabftwClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("nomad-processor")

# ── Config ───────────────────────────────────────────────────────────────────

NOMAD_API_URL = os.getenv("NOMAD_API_URL", "http://localhost:8000/nomad-oasis/api/v1")
NOMAD_PAT = os.getenv("NOMAD_PAT", "")
ELABFTW_API_URL = os.getenv("ELABFTW_API_URL", "https://elntest.ub.tum.de/api/v2")
ELABFTW_API_KEY = os.getenv("ELABFTW_API_KEY", "")
ELABFTW_TEAM = int(os.getenv("ELABFTW_TEAM", "29"))
POLL_INTERVAL = int(os.getenv("WATCH_POLL_SECONDS", "60"))
PROCESSED_LOG = "/app/logs/nomad-processor-processed.json"


def load_processed() -> set:
    """Load set of already-processed upload IDs."""
    try:
        with open(PROCESSED_LOG) as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def save_processed(upload_id: str, processed: set):
    processed.add(upload_id)
    try:
        with open(PROCESSED_LOG, "w") as f:
            json.dump(list(processed), f)
    except Exception as e:
        logger.warning(f"Could not save processed log: {e}")


def nomad_get(path: str) -> Optional[dict]:
    """GET a NOMAD API endpoint."""
    import requests as req
    url = f"{NOMAD_API_URL.rstrip('/')}/{path.lstrip('/')}"
    try:
        r = req.get(url, headers={"Authorization": f"Bearer {NOMAD_PAT}"}, timeout=15)
        if r.status_code in (200, 201):
            return r.json()
        logger.warning(f"NOMAD GET {path}: {r.status_code}")
        return None
    except Exception as e:
        logger.error(f"NOMAD GET error: {e}")
        return None


def nomad_patch(path: str, data: dict) -> bool:
    """PATCH a NOMAD API endpoint."""
    import requests as req
    url = f"{NOMAD_API_URL.rstrip('/')}/{path.lstrip('/')}"
    try:
        r = req.patch(url, json=data,
                      headers={"Authorization": f"Bearer {NOMAD_PAT}"}, timeout=15)
        return r.status_code in (200, 201, 204)
    except Exception as e:
        logger.error(f"NOMAD PATCH error: {e}")
        return False


def read_upload_file(upload_files_server_path: str, filename: str) -> Optional[io.BytesIO]:
    """Read a file from the NOMAD staging directory."""
    # Try direct staging path (when running inside container)
    staging_path = Path(upload_files_server_path) / filename
    if staging_path.exists():
        return io.BytesIO(staging_path.read_bytes())

    # Try raw/ subdirectory (NOMAD staging layout)
    raw_path = Path(upload_files_server_path) / "raw" / filename
    if raw_path.exists():
        return io.BytesIO(raw_path.read_bytes())

    # Fallback: try the raw file API
    logger.debug(f"Staging path not found: {staging_path} (raw: {raw_path})")
    return None


# ── Processing ───────────────────────────────────────────────────────────────


def process_upload(upload: dict, elab_item_id: Optional[int] = None) -> Dict[str, Any]:
    """Process a single NOMAD TGA upload: parse → compute → push to elabFTW."""
    # Some API responses wrap data under 'data' key
    if "data" in upload and isinstance(upload["data"], dict):
        upload = upload["data"]

    upload_id = upload.get("upload_id", "")
    sample_name = upload.get("upload_name", "Unknown")
    server_path = upload.get("upload_files_server_path", "")
    mainfile = upload.get("mainfile", "")

    # Path translation: inside the container, the host path becomes /app/.volumes/fs/
    if server_path and server_path.startswith("/home/debian/nomad-distro-template/.volumes/fs/"):
        server_path = server_path.replace(
            "/home/debian/nomad-distro-template/.volumes/fs/",
            "/app/.volumes/fs/"
        )

    logger.info(f"Processing upload {upload_id}: {sample_name} (item {elab_item_id})")

    # Find the CSV file in the upload
    files_list = upload.get("files", [])
    if not files_list and mainfile:
        files_list = [mainfile]

    csv_file = None
    for fname in files_list:
        if fname.endswith((".csv", ".txt", ".dat")):
            csv_file = fname
            break

    if not csv_file:
        # Try to find by listing staging directory
        if server_path:
            try:
                sp = Path(server_path)
                if sp.exists():
                    # Check direct files
                    for f in sp.iterdir():
                        if f.suffix.lower() in (".csv", ".txt", ".dat"):
                            csv_file = f.name
                            break
                    # Check raw/ subdirectory (NOMAD staging layout)
                    if not csv_file:
                        raw_dir = sp / "raw"
                        if raw_dir.exists():
                            for f in raw_dir.iterdir():
                                if f.suffix.lower() in (".csv", ".txt", ".dat"):
                                    csv_file = f.name
                                    break
            except Exception:
                pass

    if not csv_file:
        logger.warning(f"No CSV found in upload {upload_id}")
        return {"status": "skipped", "reason": "no_csv"}

    # Read the CSV file
    file_data = read_upload_file(server_path, csv_file)
    if not file_data:
        logger.error(f"Cannot read {csv_file} from upload {upload_id}")
        return {"status": "error", "reason": "file_not_found"}

    # Save to temp file for the parser
    tmp_path = Path(f"/tmp/{upload_id}_{csv_file}")
    tmp_path.write_bytes(file_data.read())

    try:
        result = _process_file(str(tmp_path), elab_item_id, sample_name, upload_id)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()

    # Update NOMAD metadata with elabftw URL (skipped: PATCH on uploads returns 405 in v1.4.2)
    if result.get("status") == "completed" and result.get("elabftw_url"):
        logger.info(f"Processing complete. elabFTW: {result['elabftw_url']}")

    return result


def _process_file(filepath: str, elab_item_id: Optional[int], sample_name: str, upload_id: str = "") -> dict:
    """Parse, compute, push to elabFTW using shared processor module."""
    from instrument_data.processor import process_tga_file
    return process_tga_file(
        filepath=filepath,
        elab_item_id=elab_item_id,
        sample_name=sample_name,
        upload_id=upload_id,
        nomad_url=f"https://researchmcp.duckdns.org/nomad-oasis/gui/user/uploads/{upload_id}",
        elabftw_api_key=ELABFTW_API_KEY,
        elabftw_team=ELABFTW_TEAM,
    )


def _compute_tga(signals: Dict[str, List[float]], metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Compute TGA results (adapted from instrument_ingest.py)."""
    import numpy as np
    result: Dict[str, Any] = {"steps": [], "summary": {}}
    temp_key = _find_signal(signals, ["temperature", "temp", "t"])
    mass_key = _find_signal(signals, ["weight", "mass", "mg", "weight_%", "wt_%"])
    if not temp_key or not mass_key:
        return result
    temp = np.array(signals[temp_key], dtype=float)
    mass = np.array(signals[mass_key], dtype=float)
    valid = np.isfinite(temp) & np.isfinite(mass)
    temp, mass = temp[valid], mass[valid]
    if len(temp) < 5:
        return result
    mass_max = np.nanmax(mass)
    mass_pct = (mass / mass_max) * 100 if mass_max > 1 else mass * 100
    dtg = np.gradient(mass_pct, temp)
    mid_idx = len(mass_pct) // 2
    # Onset
    steepest_idx = int(np.argmin(dtg))
    if 5 <= steepest_idx <= len(temp) - 5:
        t0, m0 = temp[steepest_idx], mass_pct[steepest_idx]
        baseline_end = np.mean(mass_pct[-len(mass_pct)//10:])
        if abs(dtg[steepest_idx]) > 1e-10:
            onset = t0 + (baseline_end - m0) / dtg[steepest_idx]
            result["summary"]["onset_temperature_c"] = round(float(onset), 1)
    # Residue
    max_t_idx = np.argmin(np.abs(temp - min(800, np.nanmax(temp))))
    result["summary"]["residue_pct"] = round(float(mass_pct[max_t_idx]), 1)
    # Mass loss steps
    window = max(3, len(dtg) // 100)
    if window % 2 == 0:
        window += 1
    kernel = np.ones(window) / window
    dtg_smooth = np.convolve(dtg, kernel, mode="same")
    threshold = np.std(dtg_smooth) * 1.5
    if threshold > 0.001:
        peak_indices = []
        i = 1
        while i < len(dtg_smooth) - 1:
            if dtg_smooth[i] < -threshold and dtg_smooth[i] < dtg_smooth[i-1] and dtg_smooth[i] < dtg_smooth[i+1]:
                peak_indices.append(i)
                i += max(window, 10)
            i += 1
        prev_end = 0
        steps = []
        for idx in peak_indices:
            peak_temp = temp[idx]
            start_idx = max(prev_end, idx - 20)
            for j in range(idx, start_idx, -1):
                if j <= 0 or dtg_smooth[j] >= -threshold * 0.1:
                    start_idx = j; break
            end_idx = min(len(dtg) - 1, idx + 20)
            for j in range(idx, end_idx):
                if j >= len(dtg_smooth) - 1 or dtg_smooth[j] >= -threshold * 0.1:
                    end_idx = j; break
            mass_start = mass_pct[min(start_idx, len(mass_pct)-1)]
            mass_end = mass_pct[min(end_idx, len(mass_pct)-1)]
            ml = (mass_start - mass_end) / np.nanmax(mass_pct) * 100 if np.nanmax(mass_pct) > 0 else 0
            steps.append({
                "peak_temperature_c": round(float(peak_temp), 1),
                "mass_loss_pct": round(float(ml), 2),
                "assignment": _assign_step(peak_temp),
            })
            prev_end = end_idx
        if steps:
            result["steps"] = steps
            result["summary"]["mass_loss_steps"] = len(steps)
            result["summary"]["total_mass_loss_pct"] = round(sum(s.get("mass_loss_pct", 0) for s in steps), 1)
    return result


def _find_signal(signals: Dict, candidates: List[str]) -> Optional[str]:
    for c in candidates:
        if c in signals:
            return c
    for k in signals:
        for c in candidates:
            if c in k.lower():
                return k
    return None


def _assign_step(temp: float) -> str:
    if temp < 150: return "moisture / solvent evaporation"
    elif temp < 250: return "low molecular weight volatiles"
    elif temp < 400: return "side-chain / oligomer degradation"
    elif temp < 600: return "main polymer backbone degradation"
    elif temp < 800: return "carbonization / char formation"
    return "high-temperature residue decomposition"


def _generate_plot(fmt: str, signals: Dict, computed: Dict) -> Optional[bytes]:
    import numpy as np
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    sigs = computed.get("_signals", {})
    if not sigs:
        # Build signals from raw data
        temp_key = _find_signal(signals, ["temperature", "temp", "t"])
        mass_key = _find_signal(signals, ["weight", "mass", "mg", "weight_%", "wt_%"])
        if not temp_key or not mass_key:
            return None
        temp = np.array(signals[temp_key], dtype=float)
        mass = np.array(signals[mass_key], dtype=float)
        valid = np.isfinite(temp) & np.isfinite(mass)
        temp, mass = temp[valid], mass[valid]
        if len(temp) < 5:
            return None
        mass_pct = (mass / np.nanmax(mass)) * 100
        dtg_val = np.gradient(mass_pct, temp)
        sigs = {"temperature": temp, "mass_pct": mass_pct, "dtg": dtg_val}
    else:
        temp = np.array(sigs["temperature"])
        mass_pct = np.array(sigs["mass_pct"])
        dtg_val = np.array(sigs["dtg"])
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8), sharex=True)
    ax1.plot(temp, mass_pct, "b-", lw=1.2, label="TG")
    ax1.set_ylabel("Mass (%)"); ax1.grid(True, alpha=0.3); ax1.legend()
    onset = computed.get("summary", {}).get("onset_temperature_c")
    if onset:
        ax1.axvline(x=onset, color="gray", ls="--", alpha=0.5)
    ax2.plot(temp, dtg_val, "r-", lw=1.2, label="DTG")
    ax2.set_xlabel("Temperature (°C)"); ax2.set_ylabel("dm/dT (%/°C)")
    ax2.grid(True, alpha=0.3); ax2.legend()
    for step in computed.get("steps", []):
        peak = step.get("peak_temperature_c")
        ml = step.get("mass_loss_pct", 0)
        if peak and ml > 1:
            ax2.axvline(x=peak, color="gray", ls=":", alpha=0.3)
    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def _build_body(sample_name: str, fmt: str, computed: Dict,
                plot_url: str = "", elabftw_url: str = "") -> str:
    summary = computed.get("summary", {})
    steps = computed.get("steps", [])
    body = """<div style="font-family:sans-serif;max-width:800px;">
<h3>TGA Analysis Report</h3>
<table style="width:100%;border-collapse:collapse;margin:12px 0;"><tr>"""
    for label, val in [
        ("Sample", sample_name),
        ("Onset", f'{summary.get("onset_temperature_c","—")} °C'),
        ("Residue", f'{summary.get("residue_pct","—")} %'),
        ("Mass Loss Steps", str(summary.get("mass_loss_steps","—"))),
    ]:
        body += f'<td style="border:1px solid #e2e8f0;padding:10px;text-align:center;"><div style="font-size:11px;color:#64748b;">{label}</div><div style="font-size:16px;font-weight:600;">{val}</div></td>'
    body += "</tr></table>"
    if plot_url:
        body += f'<img src="{plot_url}" style="max-width:100%;border:1px solid #e2e8f0;border-radius:8px;">'
    if steps:
        body += '<h4>Mass Loss Steps</h4><table style="width:100%;border-collapse:collapse;font-size:12px;"><tr style="background:#f1f5f9;"><th>#</th><th>Peak (°C)</th><th>Mass Loss (%)</th><th>Assignment</th></tr>'
        for i, s in enumerate(steps, 1):
            body += f'<tr><td>{i}</td><td>{s.get("peak_temperature_c","—")}</td><td>{s.get("mass_loss_pct","—")}</td><td>{s.get("assignment","")}</td></tr>'
        body += "</table>"
    body += f'<p style="color:#94a3b8;font-size:10px;margin-top:12px;">Processed: {datetime.now().strftime("%Y-%m-%d %H:%M")}</p></div>'
    return body


# ── Polling ──────────────────────────────────────────────────────────────────


def watch_cycle() -> int:
    """Poll NOMAD for new TGA uploads and process them."""
    processed = load_processed()
    logger.info(f"Already processed: {len(processed)} uploads")

    result = nomad_get("uploads?limit=20&order_by=upload_create_time&order=desc")
    if not result:
        logger.warning("Could not fetch uploads list")
        return 0

    count = 0
    for upload in result.get("data", []):
        upload_id = upload.get("upload_id", "")
        if upload_id in processed:
            continue
        if upload.get("process_status") != "SUCCESS":
            continue  # skip until processing completes

        upload_name = upload.get("upload_name", "")

        # Extract elab_item_id from filename (_itemXXXX)
        elab_item_id = None
        import re
        m = re.search(r'_item(\d+)', upload_name)
        if m:
            elab_item_id = int(m.group(1))

        logger.info(f"Found new upload: {upload_id} ({upload_name}) item={elab_item_id}")
        res = process_upload(upload, elab_item_id)
        logger.info(f"  → {res.get('status')}")
        save_processed(upload_id, processed)
        count += 1

    return count


def main():
    p = argparse.ArgumentParser(description="NOMAD TGA Processor")
    p.add_argument("mode", choices=["watch", "process"], help="watch=continuous, process=one-shot")
    p.add_argument("upload_id", nargs="?", help="Upload ID for one-shot processing")
    args = p.parse_args()

    if args.mode == "process":
        if not args.upload_id:
            logger.error("upload_id required for process mode")
            return 1
        upload = nomad_get(f"uploads/{args.upload_id}")
        if not upload:
            logger.error(f"Upload not found: {args.upload_id}")
            return 1
        # Extract elab_item_id from upload name
        upload_name = upload.get("data", upload).get("upload_name", "")
        import re
        m = re.search(r'_item(\d+)', upload_name)
        elab_item_id = int(m.group(1)) if m else None
        res = process_upload(upload, elab_item_id)
        logger.info(f"Result: {res.get('status')}")
        return 0 if res.get("status") == "completed" else 1

    if args.mode == "watch":
        logger.info(f"NOMAD TGA Processor watching (poll {POLL_INTERVAL}s)")
        try:
            while True:
                try:
                    watch_cycle()
                except Exception as e:
                    logger.error(f"Cycle error: {e}")
                time.sleep(POLL_INTERVAL)
        except KeyboardInterrupt:
            logger.info("Stopped.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
