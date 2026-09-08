"""Parser for TRIOS-exported instrument data files (CSV/TXT).

Handles the tab-separated export format from TA Instruments TRIOS software,
which uses `[Section]` headers and key-value metadata before the signal data.

Supported instrument types:
- TGA (thermogravimetric analysis)
- DMA (dynamic mechanical analysis)
- FTIR (Fourier-transform infrared spectroscopy)
- MS (mass spectrometry)

Usage:
    from instrument_data.parser import parse_file, detect_format

    result = parse_file("TGA_Polymer-X_20251031.csv")
    print(result["metadata"]["sample_name"])
    print(result["signals"]["temperature"][:5])
"""
from __future__ import annotations

import csv
import io
import re
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, TextIO, Tuple


# ── Public API ───────────────────────────────────────────────────────────────

def detect_format(filepath: str) -> Optional[str]:
    """Detect instrument type from file content.

    Returns 'tga', 'dma', 'ftir', 'ms', or None if unknown.
    """
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        head = f.read(4096)

    head_lower = head.lower()

    # Check for instrument type indicators in header metadata
    if any(kw in head_lower for kw in ["tga", "thermogravimetric"]):
        return "tga"
    if any(kw in head_lower for kw in ["dma", "dynamic mechanical"]):
        return "dma"
    if any(kw in head_lower for kw in ["ftir", "fourier transform", "infrared"]):
        return "ftir"
    if any(kw in head_lower for kw in ["mass spectrometer", "mass spec"]):
        return "ms"

    # Check instrument type field
    for line in head.splitlines():
        if line.startswith("Instrument type") or line.startswith("Instrument name"):
            val = line.split("\t", 1)[-1].strip().lower()
            if "tga" in val:
                return "tga"
            if "dma" in val:
                return "dma"

    return None


def parse_file(filepath: str) -> Dict[str, Any]:
    """Parse a TRIOS-exported CSV/TXT file.

    Returns dict with:
        format: detected instrument type ('tga', 'dma', etc.)
        metadata: dict of key-value pairs from header
        signals: dict of signal_name -> list[float]
        signal_units: dict of signal_name -> unit string
        columns: list of column header names
        raw_header: full header text before data section
    """
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    fmt = detect_format(filepath)
    lines = content.splitlines()

    # Split into header and data sections
    header_lines, data_lines, step_info = _split_sections(lines)

    # Parse header metadata
    metadata = _parse_header(header_lines)

    # Find the data section: after [step] header
    if data_lines is None:
        # Try to find data after column headers
        data_lines, columns, units = _find_data_section(header_lines)
    else:
        # Parse from explicit [step] section
        columns, units, data_lines = _parse_step_section(data_lines, step_info)

    # Parse tabular data
    signals, signal_units = _parse_data_rows(data_lines, columns, units)

    # Add format-specific computed values
    result = {
        "format": fmt,
        "metadata": metadata,
        "signals": signals,
        "signal_units": signal_units,
        "columns": columns,
        "raw_header": "\n".join(header_lines),
    }

    return result


def normalize_mass_unit(value_str: str) -> Tuple[float, str]:
    """Parse a value+unit string like '53.504 mg' -> (53.504, 'mg')."""
    value_str = value_str.strip()
    m = re.match(r"([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s*(.*)", value_str)
    if m:
        return float(m.group(1)), m.group(2).strip()
    return 0.0, ""


def parse_datetime(value_str: str) -> Optional[datetime]:
    """Parse TRIOS date/time formats."""
    formats = [
        "%m/%d/%Y",
        "%m/%d/%Y %I:%M:%S %p",
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(value_str.strip(), fmt)
        except (ValueError, AttributeError):
            continue
    return None


# ── Internal parsing ─────────────────────────────────────────────────────────

def _split_sections(lines: List[str]) -> Tuple[List[str], Optional[List[str]], Optional[str]]:
    """Split file lines into header and data sections.

    Returns (header_lines, data_lines, step_info).
    data_lines is None if no explicit [step] section found.
    """
    header = []
    step_start = None
    step_info = None

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[step]"):
            step_info = stripped
            step_start = i + 1  # skip the [step] line
            break
        header.append(line)

    if step_start is not None:
        # Skip info line after [step]
        if step_start < len(lines):
            step_info_line = lines[step_start].strip()
            step_start += 1
        else:
            step_info_line = ""
        data_lines = lines[step_start:] if step_start < len(lines) else []
        return header, data_lines, step_info_line

    return header, None, None


def _parse_header(header_lines: List[str]) -> Dict[str, Any]:
    """Parse key-value pairs and section metadata from header."""
    metadata: Dict[str, Any] = {}
    current_section = "general"

    for line in header_lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Section header
        if stripped.startswith("[") and stripped.endswith("]"):
            current_section = stripped[1:-1].lower().replace(" ", "_")
            continue

        # Key-value pair (tab-separated)
        if "\t" in stripped:
            key, _, value = stripped.partition("\t")
            key_stripped = key.strip().lower().replace(" ", "_")
            metadata[key_stripped] = value.strip()
        elif "=" in stripped:
            key, _, value = stripped.partition("=")
            metadata[key.strip().lower().replace(" ", "_")] = value.strip()
        else:
            metadata[f"{current_section}_raw"] = stripped

    return metadata


def _find_data_section(header_lines: List[str]) -> Tuple[List[str], List[str], List[str]]:
    """Fallback: find column headers and data by scanning for numeric rows."""
    columns = []
    units = []
    data_start = None

    for i, line in enumerate(header_lines):
        stripped = line.strip()
        # Look for a row that looks like column headers (alphabetic + special chars)
        if stripped and "\t" in stripped and not stripped.startswith("["):
            parts = stripped.split("\t")
            # Check if next line looks like units
            if i + 1 < len(header_lines):
                next_line = header_lines[i + 1].strip()
                next_parts = next_line.split("\t")
                if len(next_parts) == len(parts) and all(
                    _looks_like_unit(p) for p in next_parts
                ):
                    columns = parts
                    units = next_parts
                    data_start = i + 2
                    break

    data_lines = header_lines[data_start:] if data_start else []
    return data_lines, columns, units


def _parse_step_section(
    data_lines: List[str], step_info_line: str
) -> Tuple[List[str], List[str], List[str]]:
    """Parse the [step] section: column headers, units, data."""
    columns = []
    units = []
    data = []

    if not data_lines:
        return [], [], []

    # First line is column headers
    if data_lines:
        columns = [c.strip() for c in data_lines[0].split("\t")]
        data_lines = data_lines[1:]

    # Second line is units
    if data_lines:
        units = [u.strip() for u in data_lines[0].split("\t")]
        data_lines = data_lines[1:]

    # Remaining are data rows until empty line or section
    for line in data_lines:
        stripped = line.strip()
        if not stripped:
            break
        data.append(stripped)

    return columns, units, data


def _parse_data_rows(
    data_lines: List[str], columns: List[str], units: List[str]
) -> Tuple[Dict[str, List[float]], Dict[str, str]]:
    """Parse tab-separated numeric data rows."""
    signals: Dict[str, List[float]] = {}
    signal_units: Dict[str, str] = {}

    if not columns:
        return signals, signal_units

    # Initialize signal arrays
    normalized_cols = [_normalize_column_name(c) for c in columns]
    for col in normalized_cols:
        signals[col] = []

    for i, u in enumerate(units):
        if i < len(normalized_cols):
            signal_units[normalized_cols[i]] = u

    # Parse each row
    for line in data_lines:
        parts = line.split("\t")
        for i, part in enumerate(parts):
            if i < len(normalized_cols):
                try:
                    value = float(part.strip())
                    signals[normalized_cols[i]].append(value)
                except (ValueError, IndexError):
                    signals[normalized_cols[i]].append(float("nan"))

    return signals, signal_units


def _normalize_column_name(name: str) -> str:
    """Normalize signal column names to standard keys."""
    name_lower = name.strip().lower()

    mapping = {
        "angular frequency": "angular_frequency",
        "step time": "step_time",
        "time": "time",
        "time (min)": "time",
        "temperature": "temperature",
        "temperature (°c)": "temperature",
        "weight": "weight",
        "weight (mg)": "weight",
        "weight (%)": "weight_pct",
        "temperature difference": "dta",
        "temperature difference (°c)": "dta",
        "sample purge": "purge_flow",
        "sample purge (ml/min)": "purge_flow",
        "storage modulus": "storage_modulus",
        "storage modulus (mpa)": "storage_modulus",
        "loss modulus": "loss_modulus",
        "loss modulus (mpa)": "loss_modulus",
        "tan(delta)": "tan_delta",
        "tan (delta)": "tan_delta",
        "oscillation strain": "strain",
        "oscillation strain (%)": "strain",
        "oscillation stress": "stress",
        "oscillation stress (mpa)": "stress",
        "wavenumber": "wavenumber",
        "wavenumber (cm⁻¹)": "wavenumber",
        "wavenumber (cm-1)": "wavenumber",
        "absorbance": "absorbance",
        "m/z": "mz",
        "intensity": "intensity",
    }

    return mapping.get(name_lower, name_lower.replace(" ", "_").replace("-", "_").replace("(", "").replace(")", "").replace("°", ""))


def _looks_like_unit(s: str) -> bool:
    """Check if a string looks like a measurement unit."""
    s = s.strip()
    if not s:
        return False
    # Units are typically short, alphanumeric + special chars
    unit_patterns = [
        r"^[°%μmµncpkMG]?[a-zA-Z/]+$",  # °C, %, mg, mL/min, MPa, rad/s, etc.
        r"^[%°]",  # starts with % or °
    ]
    return any(re.match(p, s) for p in unit_patterns) or len(s) <= 15


# ── Convenience: extract key metadata ────────────────────────────────────────

def extract_tga_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Extract and normalize TGA-specific metadata."""
    result: Dict[str, Any] = {}

    # Sample info
    for key in ["sample_name", "sample name"]:
        if key in metadata:
            result["sample_name"] = metadata[key]
            break

    # Mass
    for key in ["sample_mass", "sample mass"]:
        if key in metadata:
            val, unit = normalize_mass_unit(metadata[key])
            result["sample_mass"] = val
            result["sample_mass_unit"] = unit
            break

    # Pan type
    for key in ["pan_type", "pan type"]:
        if key in metadata:
            result["crucible_type"] = metadata[key]
            break

    # Operator
    for key in ["operator"]:
        if key in metadata:
            result["operator"] = metadata[key]
            break

    # Instrument
    for key in ["instrument_name", "instrument name"]:
        if key in metadata:
            result["instrument_name"] = metadata[key]
            break

    # Procedure
    for key in ["procedure_name", "procedure name"]:
        if key in metadata:
            result["procedure_name"] = metadata[key]
            break
    for key in ["proceduresegments"]:
        if key in metadata:
            result["procedure_segments"] = metadata[key]
            break

    return result
