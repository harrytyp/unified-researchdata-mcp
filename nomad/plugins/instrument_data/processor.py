"""
Instrument Data Processor — shared normalizer module for TGA/DMA/FTIR/MS.

This module contains the core processing logic that's used by:
1. The NOMAD normalizer (triggered via entry normalize())
2. The poller script (nomad_processor.py)

Functions are self-contained so they can be called from any context.
"""
from __future__ import annotations

import io
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("instrument-processor")

# Import from sibling modules
from instrument_data.parser import detect_format, parse_file, extract_tga_metadata
from instrument_data.elabftw_client import ElabftwClient


# ── Configuration ────────────────────────────────────────────────────────────


DEFAULT_ELABFTW_URL = "https://elntest.ub.tum.de/api/v2"
DEFAULT_ELABFTW_TEAM = 29
DEFAULT_NOMAD_URL = "https://researchmcp.duckdns.org/nomad-oasis"


# ── Signal helpers ───────────────────────────────────────────────────────────


def _find_signal(signals: Dict, candidates: List[str]) -> Optional[str]:
    """Find a signal key by checking candidates and substring matching."""
    for c in candidates:
        if c in signals:
            return c
    for k in signals:
        for c in candidates:
            if c in k.lower():
                return k
    return None


def _assign_step(temp: float) -> str:
    """Assign a chemical interpretation to a mass loss step by temperature."""
    if temp < 150:
        return "moisture / solvent evaporation"
    elif temp < 250:
        return "low molecular weight volatiles"
    elif temp < 400:
        return "side-chain / oligomer degradation"
    elif temp < 600:
        return "main polymer backbone degradation"
    elif temp < 800:
        return "carbonization / char formation"
    return "high-temperature residue decomposition"


# ── Computation ──────────────────────────────────────────────────────────────


def compute_tga(signals: Dict[str, List[float]],
                metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Compute TGA results from parsed signal data.

    Args:
        signals: Dict of signal_name -> list of float values
        metadata: Dict of parsed metadata fields

    Returns:
        Dict with 'summary' (onset, residue, Td5, Td10, dtg_max) and
        'steps' (list of mass loss step dicts) and '_signals' for plotting.
    """
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

    # ── Onset ──
    steepest_idx = int(np.argmin(dtg))
    if 5 <= steepest_idx <= len(temp) - 5:
        t0, m0 = temp[steepest_idx], mass_pct[steepest_idx]
        baseline_end = np.mean(mass_pct[-len(mass_pct)//10:])
        if abs(dtg[steepest_idx]) > 1e-10:
            onset = t0 + (baseline_end - m0) / dtg[steepest_idx]
            result["summary"]["onset_temperature_c"] = round(float(onset), 1)

    # ── Residue ──
    residue = mass_pct[-1] if len(mass_pct) > 0 else 0
    result["summary"]["residue_mass_pct"] = round(float(residue), 2)

    # ── Td5 / Td10 ──
    for label, target in [("mass_loss_5pct", 95), ("mass_loss_10pct", 90)]:
        if mass_pct[0] >= target:
            idx = np.where(mass_pct <= target)[0]
            if len(idx) > 0:
                result["summary"][label] = round(float(temp[idx[0]]), 1)

    # ── DTG max ──
    if len(dtg) > 0:
        result["summary"]["dtg_max"] = round(float(np.min(dtg)), 3)

    # ── Mass loss steps via DTG peak detection ──
    if len(dtg) > 20:
        dtg_smooth = np.convolve(dtg, np.ones(5)/5, mode="same")
        threshold = np.std(dtg_smooth) * 1.5
        # Find peaks (local minima in DTG = max mass loss rate)
        peak_indices = []
        for i in range(5, len(dtg_smooth) - 5):
            if dtg_smooth[i] < -threshold and dtg_smooth[i] == np.min(dtg_smooth[max(0, i-5):min(len(dtg_smooth), i+6)]):
                # Avoid nearby peaks
                if not peak_indices or i - peak_indices[-1] > 10:
                    peak_indices.append(i)

        prev_end = 0
        steps = []
        for idx in peak_indices:
            peak_temp = temp[idx]
            start_idx = max(prev_end, idx - 20)
            for j in range(idx, start_idx, -1):
                if j <= 0 or dtg_smooth[j] >= -threshold * 0.1:
                    start_idx = j
                    break
            end_idx = min(len(dtg) - 1, idx + 20)
            for j in range(idx, end_idx):
                if j >= len(dtg_smooth) - 1 or dtg_smooth[j] >= -threshold * 0.1:
                    end_idx = j
                    break
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
            result["summary"]["total_mass_loss_pct"] = round(
                sum(s.get("mass_loss_pct", 0) for s in steps), 1)

    # Store processed signals for plotting
    result["_signals"] = {
        "temperature": temp.tolist(),
        "mass_pct": mass_pct.tolist(),
        "dtg": dtg.tolist(),
    }
    return result


# ── Plot generation ──────────────────────────────────────────────────────────


def generate_plot(signals: Dict[str, List[float]],
                  computed: Dict[str, Any]) -> Optional[bytes]:
    """Generate a 2-panel TGA plot (TG + DTG).

    Returns PNG bytes or None on failure.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    sigs = computed.get("_signals", {})
    if not sigs:
        # Build from raw signals
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
    # TG panel
    ax1.plot(temp, mass_pct, "b-", lw=1.2, label="TG")
    ax1.set_ylabel("Mass (%)")
    ax1.grid(True, alpha=0.3)
    ax1.legend()
    onset = computed.get("summary", {}).get("onset_temperature_c")
    if onset:
        ax1.axvline(x=onset, color="gray", ls="--", alpha=0.5)
    # DTG panel
    ax2.plot(temp, dtg_val, "r-", lw=1.2, label="DTG")
    ax2.set_xlabel("Temperature (°C)")
    ax2.set_ylabel("dm/dT (%/°C)")
    ax2.grid(True, alpha=0.3)
    ax2.legend()
    # Annotation
    residue = computed.get("summary", {}).get("residue_mass_pct")
    if residue:
        ax1.annotate(f"Residue: {residue}%", xy=(temp[-1], mass_pct[-1]),
                     fontsize=9, color="green",
                     xytext=(5, 5), textcoords="offset points")
    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


# ── elabFTW push ─────────────────────────────────────────────────────────────


def push_tga_to_elabftw(
    elab_item_id: int,
    sample_name: str,
    signals: Dict[str, List[float]],
    computed: Dict[str, Any],
    nomad_url: str,
    plot_png: Optional[bytes] = None,
    elabftw_api_url: str = DEFAULT_ELABFTW_URL,
    elabftw_api_key: str = "",
    elabftw_team: int = DEFAULT_ELABFTW_TEAM,
    upload_id: str = "",
) -> Tuple[bool, str]:
    """Push TGA results to an elabFTW item.

    Args:
        elab_item_id: elabFTW item ID
        sample_name: Sample name
        signals: Parsed signal data
        computed: Computed TGA results
        nomad_url: URL to the NOMAD upload
        plot_png: Optional PNG bytes for the plot
        elabftw_api_key: elabFTW API key
        elabftw_team: elabFTW team ID

    Returns:
        (success, elabftw_url)
    """
    if not elabftw_api_key:
        return False, ""

    elab = ElabftwClient(
        api_url=elabftw_api_url,
        api_key=elabftw_api_key,
        team=elabftw_team,
    )
    elab.set_item_running(elab_item_id)

    # Upload plot and build download URL
    plot_url = ""
    if plot_png:
        plot_tmp = Path(f"/tmp/{elab_item_id}_plot.png")
        plot_tmp.write_bytes(plot_png)
        try:
            elab.upload_file_to_item(elab_item_id, str(plot_tmp))
        except Exception:
            pass
        # Query uploads list for long_name (elabFTW returns empty body on upload)
        try:
            import requests as _req
            resp = _req.get(
                f"{elabftw_api_url}/items/{elab_item_id}/uploads",
                headers={"Authorization": elabftw_api_key},
                timeout=15,
            )
            if resp.status_code == 200:
                for upl in (resp.json() or []):
                    if upl.get("real_name", "").endswith(".png"):
                        name = upl.get("real_name", "plot.png")
                        long_name = upl.get("long_name", "")
                        storage = upl.get("storage", 1)
                        if long_name:
                            plot_url = f"app/download.php?name={name}&f={long_name}&storage={storage}"
                            break
        except Exception:
            pass
        if plot_tmp.exists():
            plot_tmp.unlink()

    # Push results via the elabFTW client method
    try:
        ok = elab.push_tga_results_to_item(
            item_id=elab_item_id,
            sample_name=sample_name,
            signals=signals,
            computed=computed,
            nomad_url=nomad_url,
            plot_url=plot_url,
        )
    except Exception:
        ok = False

    if ok:
        elab_url = f"{elabftw_api_url.rstrip('/api/v2')}/database.php?mode=view&id={elab_item_id}"
        return True, elab_url
    return False, ""


# ── File processing (main entry point) ───────────────────────────────────────


def process_tga_file(
    filepath: str,
    elab_item_id: Optional[int] = None,
    sample_name: str = "Unknown",
    upload_id: str = "",
    nomad_url: str = "",
    elabftw_api_key: str = "",
    elabftw_team: int = DEFAULT_ELABFTW_TEAM,
) -> Dict[str, Any]:
    """Process a TGA CSV/TXT file end-to-end: parse → compute → plot → push.

    This is the main entry point for both the poller and the NOMAD normalizer.

    Args:
        filepath: Path to the CSV/TXT file
        elab_item_id: Optional elabFTW item ID to push results to
        sample_name: Fallback sample name
        upload_id: NOMAD upload ID (for building URLs)
        nomad_url: NOMAD base URL
        elabftw_api_key: elabFTW API key (required for push)

    Returns:
        Dict with processing result
    """
    result = {"file": filepath, "status": "pending", "sample_name": sample_name}

    path = Path(filepath)
    if not path.exists():
        return {"status": "error", "reason": "file_not_found"}

    # 1. Detect format
    fmt = detect_format(str(path))
    if not fmt:
        return {"status": "skipped", "reason": "unknown_format"}

    # 2. Parse
    try:
        parsed = parse_file(str(path))
    except Exception as e:
        return {"status": "error", "reason": f"parse_error: {e}"}

    signals = parsed.get("signals", {})
    metadata = parsed.get("metadata", {})
    norm = extract_tga_metadata(metadata)
    sample_name = norm.get("sample_name", sample_name)
    result["sample_name"] = sample_name
    result["format"] = fmt

    # 3. Compute
    computed = compute_tga(signals, metadata)
    result["computed"] = computed

    # 4. Generate plot
    plot_png = None
    try:
        plot_png = generate_plot(signals, computed)
    except Exception as e:
        logger.warning(f"Plot generation failed: {e}")

    # 5. Push to elabFTW
    if elab_item_id and elabftw_api_key:
        success, elab_url = push_tga_to_elabftw(
            elab_item_id=elab_item_id,
            sample_name=sample_name,
            signals=signals,
            computed=computed,
            nomad_url=nomad_url,
            plot_png=plot_png,
            elabftw_api_key=elabftw_api_key,
            elabftw_team=elabftw_team,
            upload_id=upload_id,
        )
        if success:
            result["status"] = "completed"
            result["elabftw_url"] = elab_url
        else:
            result["status"] = "push_failed"
    else:
        result["status"] = "completed"  # processed without elabFTW push

    return result


# ── NOMAD Normalizer ─────────────────────────────────────────────────────────


def normalize_tga_entry(entry: Any, archive: Any, logger: Any) -> None:
    """NOMAD normalizer for TgaMeasurement.

    Called when the user toggles ``process_now`` on a TgaMeasurement entry.
    Reads the raw CSV/TXT file from the referenced NOMAD upload, parses it,
    computes results, and populates the entry's signal + result fields.

    If ELABFTW_API_KEY is set, also pushes results to the linked elabFTW item.
    """
    import os
    import requests as _req

    upload_id = getattr(entry, "source_upload_id", None)
    if not upload_id:
        logger.warning("No source_upload_id set on entry")
        return

    logger.info(f"Processing upload {upload_id} for TGA entry")

    # Fetch upload details from NOMAD
    pat = os.environ.get("NOMAD_PAT", "")
    nomad_url = os.environ.get(
        "NOMAD_API_URL",
        "http://localhost:8000/nomad-oasis/api/v1",
    )
    if not pat:
        logger.warning("NOMAD_PAT not set, cannot read upload")
        return

    try:
        resp = _req.get(
            f"{nomad_url}/uploads/{upload_id}",
            headers={"Authorization": f"Bearer {pat}"},
            timeout=15,
        )
        if resp.status_code != 200:
            logger.warning(f"Cannot fetch upload {upload_id}: {resp.status_code}")
            return
        upload_data = resp.json().get("data", resp.json())
    except Exception as e:
        logger.warning(f"Error fetching upload: {e}")
        return

    upload_name = upload_data.get("upload_name", "unknown.txt")
    server_path = upload_data.get("upload_files_server_path", "")

    # Path translation for container
    if server_path.startswith("/home/debian/nomad-distro-template/.volumes/fs/"):
        server_path = server_path.replace(
            "/home/debian/nomad-distro-template/.volumes/fs/",
            "/app/.volumes/fs/"
        )

    # Find the CSV file in staging
    csv_file = None
    sp = Path(server_path)
    if sp.exists():
        for f in sp.iterdir():
            if f.suffix.lower() in (".csv", ".txt", ".dat"):
                csv_file = f.name
                break
        if not csv_file:
            raw_dir = sp / "raw"
            if raw_dir.exists():
                for f in raw_dir.iterdir():
                    if f.suffix.lower() in (".csv", ".txt", ".dat"):
                        csv_file = f.name
                        break

    if not csv_file:
        logger.warning(f"No CSV found in upload {upload_id}")
        return

    # Read the file
    staging_path = Path(server_path) / csv_file
    raw_path = Path(server_path) / "raw" / csv_file
    if staging_path.exists():
        file_data = staging_path.read_bytes()
    elif raw_path.exists():
        file_data = raw_path.read_bytes()
    else:
        logger.warning(f"File not found: {staging_path}")
        return

    # Write to temp file for parser
    tmp_path = Path(f"/tmp/{upload_id}_{csv_file}")
    tmp_path.write_bytes(file_data)

    try:
        # Detect format and parse
        fmt = detect_format(str(tmp_path))
        if not fmt:
            logger.warning(f"Unknown format: {csv_file}")
            return

        parsed = parse_file(str(tmp_path))
        signals = parsed.get("signals", {})
        metadata = parsed.get("metadata", {})
        sample_name = extract_tga_metadata(metadata).get(
            "sample_name", upload_name
        )

        # Compute
        computed = compute_tga(signals, metadata)

        # Generate plot
        plot_png = generate_plot(signals, computed)

        # ── Populate entry fields ──
        if not entry.results:
            from instrument_data.schema import TgaResults
            entry.results = TgaResults()
        results = entry.results

        # Summary fields
        summary = computed.get("summary", {})
        if summary.get("onset_temperature_c"):
            entry.results.onset_temperature = summary["onset_temperature_c"]
        if summary.get("residue_mass_pct"):
            entry.results.residue_mass_pct = summary["residue_mass_pct"]
        if summary.get("mass_loss_5pct"):
            entry.results.mass_loss_5pct = summary["mass_loss_5pct"]
        if summary.get("mass_loss_10pct"):
            entry.results.mass_loss_10pct = summary["mass_loss_10pct"]
        if summary.get("dtg_max"):
            entry.results.residue_mass_mg = float(abs(summary["dtg_max"]))

        # Mass loss steps
        steps_data = computed.get("steps", [])
        if steps_data:
            from instrument_data.schema import TgaStep
            entry.results.steps = []
            for sd in steps_data:
                step = TgaStep()
                step.peak_dtg_temperature = sd.get("peak_temperature_c")
                step.mass_loss_pct = sd.get("mass_loss_pct")
                step.assignment = sd.get("assignment")
                entry.results.steps.append(step)

        # Signal data
        if "temperature" in signals:
            entry.temperature_signal = signals["temperature"]
        if "weight" in signals or "mass" in signals:
            weight_key = "weight" if "weight" in signals else "mass"
            entry.weight_signal = signals[weight_key]
        if "dta" in signals:
            entry.dta_signal = signals["dta"]

        # Plot as base64
        if plot_png:
            import base64
            entry.summary_plot = base64.b64encode(plot_png).decode("ascii")

        # Source info
        entry.source_file = csv_file
        entry.original_filename = upload_name

        # ── elabFTW push ──
        api_key = os.environ.get("ELABFTW_API_KEY", "")
        team = int(os.environ.get("ELABFTW_TEAM", "29"))
        elab_url = os.environ.get(
            "ELABFTW_API_URL",
            "https://elntest.ub.tum.de/api/v2",
        )

        # Extract elab_item_id from filename
        elab_item_id = None
        m = re.search(r'_item(\d+)', upload_name)
        if m:
            elab_item_id = int(m.group(1))

        if elab_item_id and api_key:
            nomad_gui_url = (
                f"https://researchmcp.duckdns.org/nomad-oasis/"
                f"gui/user/uploads/{upload_id}"
            )
            push_tga_to_elabftw(
                elab_item_id=elab_item_id,
                sample_name=sample_name,
                signals=signals,
                computed=computed,
                nomad_url=nomad_gui_url,
                plot_png=plot_png,
                elabftw_api_key=api_key,
                elabftw_team=team,
                upload_id=upload_id,
            )

        logger.info(f"TGA entry processing complete for {upload_id}")

    finally:
        if tmp_path.exists():
            tmp_path.unlink()
