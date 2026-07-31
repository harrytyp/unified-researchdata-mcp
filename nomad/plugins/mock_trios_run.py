#!/usr/bin/env python3
"""Mock TRIOS instrument run. Generates a realistic CSV/TXT export file from
elabFTW experiment parameters, as if the TGA instrument had just run.

Purpose: demonstrate the full A-to-Z pipeline without a physical instrument.

Usage:
    # Generate a mock TGA export from an existing elabFTW experiment
    python mock_trios_run.py --experiment 4689 --outdir /home/debian/instrument-exports/

    # Generate with random/default parameters (no elabFTW experiment needed)
    python mock_trios_run.py --outdir /tmp/mock-exports/

    # This creates a CSV file in the watch folder.
    # Then run: instrument_ingest.py watch /home/debian/instrument-exports/
    # to see the full pipeline (parse -> compute -> push back to elabFTW).
"""
from __future__ import annotations

import argparse
import csv
import io
import math
import os
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Add parent to path for plugin imports
_plugin_dir = Path(__file__).resolve().parent.parent / "plugins"
sys.path.insert(0, str(_plugin_dir))

from instrument_data.mock_run import generate_and_write

def fetch_experiment_params(experiment_id: int, api_key: str = "",
                            api_url: str = "https://elntest.ub.tum.de/api/v2") -> Dict[str, Any]:
    """Fetch an elabFTW experiment and extract extra_fields as parameters."""
    import json
    import requests

    headers = {"Authorization": api_key}
    resp = requests.get(f"{api_url}/experiments/{experiment_id}", headers=headers, timeout=15)
    if resp.status_code != 200:
        print(f"Warning: Could not fetch experiment {experiment_id} (HTTP {resp.status_code})")
        return {}

    exp = resp.json()
    meta_raw = exp.get("metadata")
    meta = {}
    if meta_raw:
        if isinstance(meta_raw, str):
            meta = json.loads(meta_raw)
        else:
            meta = meta_raw

    extra = meta.get("extra_fields", {})
    return {
        "sample_name": extra.get("sample_name", exp.get("title", "MockSample")),
        "sample_mass_mg": _float_or(extra.get("sample_mass_mg"), 12.5),
        "temp_start": _float_or(extra.get("temperature_start"), 30.0),
        "temp_end": _float_or(extra.get("temperature_end"), 1000.0),
        "heating_rate": _float_or(extra.get("heating_rate"), 10.0),
        "gas": extra.get("gas_atmosphere", "N2"),
        "flow_rate": _float_or(extra.get("gas_flow_rate"), 50.0),
        "crucible": extra.get("crucible_type", "Alumina"),
        "operator": extra.get("operator", "MockOperator"),
        "experiment_id": experiment_id,
    }


def _float_or(val, default: float) -> float:
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Mock TRIOS instrument run. Generates a realistic CSV/TXT "
                    "export as if the TGA had just completed a measurement.",
    )
    parser.add_argument("--experiment", type=int, default=None,
                        help="elabFTW experiment ID to pull parameters from")
    parser.add_argument("--outdir", type=str, default="/tmp/mock-exports",
                        help="Output directory for the mock CSV file")
    parser.add_argument("--api-key", type=str,
                        default=os.environ.get("ELABFTW_API_KEY", ""),
                        help="elabFTW API key")
    parser.add_argument("--api-url", type=str,
                        default=os.environ.get("ELABFTW_API_URL",
                                               "https://elntest.ub.tum.de/api/v2"),
                        help="elabFTW API URL")
    parser.add_argument("--noise", type=float, default=0.002,
                        help="Noise level for synthetic signals")
    parser.add_argument("--seed", type=int, default=42,
                        help="Random seed for reproducibility")

    args = parser.parse_args()

    # Get parameters
    if args.experiment:
        print(f"Fetching experiment {args.experiment} from elabFTW...")
        params = fetch_experiment_params(args.experiment, args.api_key, args.api_url)
        if not params:
            print("Warning: Using default parameters")
            params = {"sample_name": "FallbackSample", "sample_mass_mg": 10.0,
                      "temp_start": 30, "temp_end": 800, "heating_rate": 10,
                      "gas": "N2", "flow_rate": 40, "crucible": "Alumina",
                      "operator": "auto", "experiment_id": args.experiment}
    else:
        params = {
            "sample_name": "Polymer-X",
            "sample_mass_mg": 12.5,
            "temp_start": 30.0,
            "temp_end": 1000.0,
            "heating_rate": 10.0,
            "gas": "N2",
            "flow_rate": 50.0,
            "crucible": "Alumina",
            "operator": "MockOperator",
            "experiment_id": None,
        }

    print(f"Generating mock TGA data for: {params['sample_name']}")
    print(f"  Mass: {params['sample_mass_mg']} mg")
    print(f"  Temp: {params['temp_start']} -> {params['temp_end']} C at {params['heating_rate']} K/min")
    print(f"  Gas: {params['gas']} ({params['flow_rate']} mL/min)")
    print(f"  Crucible: {params['crucible']}")

    # Generate mock TGA data using the library function
    gen_result = generate_and_write(
        outdir=args.outdir,
        sample_name=params["sample_name"],
        sample_mass_mg=params["sample_mass_mg"],
        temp_start=params["temp_start"],
        temp_end=params["temp_end"],
        heating_rate=params["heating_rate"],
        gas=params["gas"],
        flow_rate=params["flow_rate"],
        crucible=params["crucible"],
        operator=params["operator"],
        experiment_id=params.get("experiment_id"),
        noise_level=args.noise,
        seed=args.seed,
    )

    print(f"\nWritten: {gen_result['filepath']}")
    print(f"  Signal points: ~{gen_result['signal_count']} per channel")
    print(f"  Channels: {gen_result['channels']}")
    print(f"\nNow run the pipeline:")
    print(f"  python instrument_ingest.py process {gen_result['filepath']}")
    print(f"Or watch the directory:")
    print(f"  ELABFTW_API_KEY=... python instrument_ingest.py watch {args.outdir}")


if __name__ == "__main__":
    main()
