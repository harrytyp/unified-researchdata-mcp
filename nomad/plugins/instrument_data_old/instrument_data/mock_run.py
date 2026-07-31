"""Mock TRIOS instrument run. Generates realistic TGA signal data.

Used by:
- MockInstrumentRun NOMAD schema (normalizer triggers generation on save)
- mock_trios_run.py CLI script (standalone usage)
- Demo/testing of the full instrument pipeline
"""
from __future__ import annotations

import math
import os
import random
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def generate_tga_signals(
    sample_name: str = "MockSample",
    sample_mass_mg: float = 12.5,
    temp_start: float = 30.0,
    temp_end: float = 1000.0,
    heating_rate: float = 10.0,
    gas: str = "N2",
    flow_rate: float = 50.0,
    crucible: str = "Alumina",
    operator: str = "MockOperator",
    noise_level: float = 0.002,
    seed: int = 42,
) -> Dict[str, Any]:
    """Generate synthetic TGA signal data that looks like a real TRIOS export.

    The weight curve has three mass loss steps (moisture, main degradation,
    carbonization) with realistic temperatures based on the heating rate.

    Returns a dict with 'metadata' (header key-value pairs), 'signals' (column
    arrays), 'signal_units', and 'columns'.
    """
    rng = random.Random(seed)

    # Time array
    total_time_min = (temp_end - temp_start) / heating_rate if heating_rate > 0 else 60
    num_points = int(total_time_min * 4)
    num_points = max(num_points, 50)

    time_min = [i * total_time_min / num_points for i in range(num_points)]
    temperature = [temp_start + heating_rate * t for t in time_min]

    # Normalize for curve generation
    norm_temp = [(t - temp_start) / (temp_end - temp_start) for t in temperature]

    # Weight curve: 100% at start, then stepwise losses
    weight_pct = []
    for nt in norm_temp:
        w = 100.0
        if nt > 0.12:
            fraction = min((nt - 0.12) / 0.08, 1.0)
            w -= 4.0 * fraction
        if nt > 0.40:
            fraction = min((nt - 0.40) / 0.15, 1.0)
            w -= 65.0 * fraction
        if nt > 0.70:
            fraction = min((nt - 0.70) / 0.12, 1.0)
            w -= 28.0 * fraction
            w = max(w, 3.0)
        w += rng.gauss(0, noise_level * 100)
        weight_pct.append(w)

    weight_mg = [w / 100.0 * sample_mass_mg for w in weight_pct]

    # DTA signal: derivative-like peaks at transition points
    dta = []
    for nt in norm_temp:
        d = 0.0
        d -= 0.3 * _gaussian(nt, 0.16, 0.03)
        d += 1.5 * _gaussian(nt, 0.48, 0.05)
        d += 0.4 * _gaussian(nt, 0.76, 0.06)
        d += rng.gauss(0, 0.02)
        dta.append(d)

    purge = [flow_rate] * len(time_min)
    for i in range(min(10, len(time_min))):
        purge[i] = flow_rate * (0.5 + 0.5 * i / 10)

    # Metadata header
    procedure_segments = (
        f"Ramp {heating_rate:.1f} C/min to {temp_end:.0f} C; "
        f"Isothermal 5.0 min"
    )

    metadata = {
        "filename": f"{sample_name.replace(' ', '_')}_{datetime.now():%Y%m%d}",
        "instrument_name": "0550-1823 (192.168.0.3)",
        "instrument_type": "TGA5500",
        "operator": operator,
        "rundate": datetime.now().strftime("%m/%d/%Y"),
        "sample_name": sample_name,
        "sample mass": f"{sample_mass_mg:.3f} mg",
        "pan_type": crucible,
        "procedure_name": "Char yield with gas and without air cool",
        "proceduresegments": procedure_segments,
        "trios_version": "5.1.1.46572",
        "gas_type": gas,
        "flow_rate": f"{flow_rate:.0f} mL/min",
    }

    signals = {
        "time": time_min,
        "temperature": temperature,
        "weight": weight_mg,
        "dta": dta,
        "purge_flow": purge,
        "weight_pct": weight_pct,
    }

    signal_units = {
        "time": "min",
        "temperature": "C",
        "weight": "mg",
        "dta": "C",
        "purge_flow": "mL/min",
        "weight_pct": "%",
    }

    return {
        "metadata": metadata,
        "signals": signals,
        "signal_units": signal_units,
        "columns": ["time", "temperature", "weight", "dta", "purge_flow"],
    }


def _gaussian(x: float, mu: float, sigma: float) -> float:
    return math.exp(-0.5 * ((x - mu) / sigma) ** 2)


def write_trios_export(data: Dict[str, Any], filepath: str) -> str:
    """Write synthetic data in TRIOS tab-separated export format."""
    metadata = data["metadata"]
    signals = data["signals"]
    columns = data["columns"]
    signal_units = data.get("signal_units", {})

    lines: List[str] = []

    for key, value in metadata.items():
        lines.append(f"{key}\t{value}")

    lines.append("[File Parameters]")
    lines.append(f"Name\t{metadata.get('filename', 'mock')}")
    lines.append(f"Instrument type\t{metadata.get('instrument_type', 'TGA5500')}")
    lines.append(f"Instrument serial number\t{metadata.get('instrument_name', '')}")
    lines.append(f"Instrument name\t{metadata.get('instrument_name', '')}")
    lines.append(f"Instrument location\tLab")
    lines.append(f"Company name\teConversion")
    lines.append(f"Trios version\t{metadata.get('trios_version', '5.1.1.46572')}")
    lines.append(f"File name\tC:\\Mock\\{metadata.get('filename', 'mock')}.tri")
    lines.append(f"Run date\t{metadata.get('rundate', '')} 12:00:00 PM")

    lines.append("[Procedure]")
    lines.append(f"Procedure Name\t{metadata.get('procedure_name', 'Mock Procedure')}")
    lines.append(f"Sample Name\t{metadata.get('sample_name', 'Mock')}")
    lines.append(f"Sample Mass\t{metadata.get('sample mass', '10.000 mg')}")
    lines.append(f"Pan Type\t{metadata.get('pan_type', 'Alumina')}")

    lines.append("[step]")
    lines.append("Temperature Ramp - Mock")
    col_headers = "\t".join(columns)
    lines.append(col_headers)
    units_row = "\t".join(signal_units.get(c, "") for c in columns)
    lines.append(units_row)

    n = len(signals[columns[0]])
    for i in range(n):
        row = "\t".join(f"{signals[c][i]:.6e}" for c in columns)
        lines.append(row)

    lines.append("")
    content = "\n".join(lines)

    with open(filepath, "w", encoding="utf-8", newline="") as f:
        f.write(content)

    return filepath


def generate_and_write(
    outdir: str = "/tmp/mock-exports",
    sample_name: str = "Polymer-X",
    sample_mass_mg: float = 12.5,
    temp_start: float = 30.0,
    temp_end: float = 1000.0,
    heating_rate: float = 10.0,
    gas: str = "N2",
    flow_rate: float = 50.0,
    crucible: str = "Alumina",
    operator: str = "MockOperator",
    experiment_id: Optional[int] = None,
    noise_level: float = 0.002,
    seed: int = 42,
) -> Dict[str, Any]:
    """Generate mock TGA data and write to a CSV file.

    Returns dict with 'filepath', 'signals', 'metadata', and signal statistics.
    """
    data = generate_tga_signals(
        sample_name=sample_name,
        sample_mass_mg=sample_mass_mg,
        temp_start=temp_start,
        temp_end=temp_end,
        heating_rate=heating_rate,
        gas=gas,
        flow_rate=flow_rate,
        crucible=crucible,
        operator=operator,
        noise_level=noise_level,
        seed=seed,
    )

    exp_suffix = f"_exp{experiment_id}" if experiment_id else ""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = sample_name.replace(" ", "_").replace("/", "_")
    filename = f"TGA_{safe_name}{exp_suffix}_{timestamp}.txt"

    Path(outdir).mkdir(parents=True, exist_ok=True)
    filepath = str(Path(outdir) / filename)
    write_trios_export(data, filepath)

    signal_counts = {k: len(v) for k, v in data["signals"].items()}
    peak_count = max(signal_counts.values()) if signal_counts else 0

    return {
        "filepath": filepath,
        "signals": data["signals"],
        "metadata": data["metadata"],
        "signal_count": peak_count,
        "channels": data["columns"],
    }
