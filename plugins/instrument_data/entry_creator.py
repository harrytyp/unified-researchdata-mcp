"""
NOMAD entry creation utilities for the pipeline.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

import requests as _req

logger = logging.getLogger("nomad-entry-creator")


def create_tga_entry(
    upload_id: str,
    sample_name: str,
    computed: Dict[str, Any],
    signals: Dict[str, Any],
    upload_name: str = "",
    elabftw_url: str = "",
    elab_item_id: Optional[int] = None,
    nomad_api_url: str = "http://localhost:8000/nomad-oasis/api/v1",
    pat: str = "",
) -> Optional[str]:
    """Create a TgaMeasurement entry within an existing NOMAD upload.

    PUTs a JSON entry file to the upload's entries endpoint.
    Returns the entry ID (filename) or None on failure.
    """
    if not pat:
        pat = os.environ.get("NOMAD_PAT", "")
    if not pat:
        logger.warning("NOMAD_PAT not set, cannot create entry")
        return None

    summary = computed.get("summary", {})
    steps = computed.get("steps", [])

    # Build entry data in NOMAD's structured format
    entry_data = {
        "data": {
            "m_def": "instrument_data.schema:TgaMeasurement",
            "sample": {
                "sample_name": sample_name or upload_name,
            },
            "results": {
                "onset_temperature": summary.get("onset_temperature_c"),
                "residue_mass_pct": summary.get("residue_mass_pct"),
                "mass_loss_5pct": summary.get("mass_loss_5pct"),
                "mass_loss_10pct": summary.get("mass_loss_10pct"),
                "steps": [
                    {
                        "peak_dtg_temperature": s.get("peak_temperature_c"),
                        "mass_loss_pct": s.get("mass_loss_pct"),
                        "assignment": s.get("assignment"),
                    }
                    for s in steps
                ],
            },
            "original_filename": upload_name,
            "elabftw_ref": {
                "elabftw_url": elabftw_url,
                "experiment_id": str(elab_item_id) if elab_item_id else "",
                "sync_status": "synced" if elabftw_url else "pending",
            },
        }
    }

    # Add signal data (trimmed to avoid overly large payloads)
    temp_signal = signals.get("temperature", [])
    weight_signal = signals.get("weight", signals.get("mass", []))
    if temp_signal and len(temp_signal) > 500:
        # Sample every Nth point to keep payload manageable
        step = max(1, len(temp_signal) // 500)
        entry_data["data"]["temperature_signal"] = temp_signal[::step]
        if weight_signal:
            entry_data["data"]["weight_signal"] = weight_signal[::step]
    elif temp_signal:
        entry_data["data"]["temperature_signal"] = temp_signal
        if weight_signal:
            entry_data["data"]["weight_signal"] = weight_signal

    # Entry filename (must be unique within the upload)
    entry_id = f"tga_results_{upload_id}.json"

    try:
        url = f"{nomad_api_url.rstrip('/')}/uploads/{upload_id}/entries/{entry_id}"
        resp = _req.put(
            url,
            json=entry_data,
            headers={"Authorization": f"Bearer {pat}"},
            timeout=30,
        )
        if resp.status_code in (200, 201, 204):
            logger.info(f"NOMAD entry created: {entry_id}")
            return entry_id
        else:
            logger.warning(
                f"Entry creation failed: {resp.status_code} {resp.text[:200]}"
            )
            return None
    except Exception as e:
        logger.warning(f"Entry creation error: {e}")
        return None
