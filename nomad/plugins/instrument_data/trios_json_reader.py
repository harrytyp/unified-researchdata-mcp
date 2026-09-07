"""Lightweight reader for TRIOS JSON Export files (TA Instruments).

Why this exists (instead of using ``tadatakit`` server-side):
  - The NOMAD Oasis worker has only ~3.8 GB RAM total and no internet; a
    134 MB TRIOS JSON with 88k rows must be parsed inside the Temporal
    processing workflow. ``tadatakit`` pulls in pandas + the full
    schema-generated class stack and is too heavy / risky there.
  - This module only needs ``json`` + ``numpy`` (already present in the
    NOMAD image) and reads exactly the fields we need.

Scope: parse the officially documented TRIOS JSON Export structure
(https://software.tainstruments.com/schemas/TRIOSJSONExportSchema):

  top-level: Schema, Log, Operators, Sample, Procedure, Results, StartTime, Analyses
  Results: {Processed: DataSet, Original: DataSet}
  DataSet: {Classification, ResultsSteps, ColumnHeaders, Rows}
    ColumnHeaders: {canonicalKey: {DisplayName, ValueType, Unit:{Name}}}
    Rows: [ {canonicalKey: value, ...} ]      # one object per measurement point

Locale independence: canonical keys look like ``Masse_%`` (German) or
``Weight_%`` (English) — DisplayName is localized. We map columns by
ROLE (temperature / mass-% / mass-mg / time / dtg / ramp-rate /
target-temperature / step-id), matching on a normalized DisplayName plus
the unit, with a German+English term table. Unknown columns are ignored.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# ── Column role table ────────────────────────────────────────────────────────
# Each role: display-name keywords (lowercase, unicode-normalized) + expected unit.
# The unit check is secondary (a DE/EN column of the same role always carries
# the same unit), but guards against e.g. 'Masse_mg' vs 'Masse_%'.

_ROLE_TERMS = {
    # (keywords, unit-suffix)
    "temperature": (("temperatur", "temperature"), "°c"),
    "time": (("zeit", "time"), "min"),
    "step_time": (("schrittzeit", "step time"), "min"),
    "mass_pct": (("masse", "weight", "mass"), "%"),
    "mass_mg": (("masse", "weight", "mass"), "mg"),
    "dtg": (("abl. masse", "deriv. weight", "dtg"), None),  # %/°C or %/min
    "ramp_rate": (("rampenrate", "ramp rate", "heating rate"), None),
    "target_temperature": (("zieltemperatur", "target temperature", "set point temperature"), "°c"),
    "temp_diff": (("temperaturdifferenz", "temperature difference", "dta"), "°c"),
    "power": (("leistung", "power"), "w"),
    "sample_purge": (("probenspülgas", "sample purge"), None),
    "balance_purge": (("spülgas des wägesystems", "balance purge"), None),
    "step_id": (("verfahrensschritt-id", "procedure step id", "step id"), None),
    "result_step_id": (("ergebnisse schritt-id", "results step id"), None),
}

# Canonical role names we actually consume
SIGNAL_ROLES = ("temperature", "time", "mass_pct", "mass_mg", "dtg")


def _norm(s: str) -> str:
    """Lowercase + collapse whitespace/underscores for tolerant matching."""
    import unicodedata
    s = unicodedata.normalize("NFKD", s or "")
    s = s.replace("_", " ").replace("-", " ").lower()
    return " ".join(s.split())


def _unit_of(header: Dict[str, Any]) -> str:
    u = header.get("Unit") or {}
    return _norm(u.get("Name", "") if isinstance(u, dict) else "")


def _classify_column(key: str, header: Dict[str, Any]) -> Optional[str]:
    """Return the role of a ColumnHeaders entry, or None if irrelevant.

    Exact-canonical-key matches win over substring matches so that
    'Temperatur_°C' is chosen over '1/Temperatur_1/K', 'Zieltemperatur_°C'
    or 'Temperaturdifferenz_°C'; and 'Masse_%' over 'Abl. Masse_% / °C'
    (DTG). The canonical key is '{DisplayName}_{Unit}' — locale-dependent
    (German/English), so we still match on normalized display names, but
    score exactness.
    """
    if (header.get("ValueType") or "").lower() == "uuid":
        return None
    display = _norm(header.get("DisplayName", key))
    unit = _unit_of(header)
    # Exact-canonical key or exact display-name matches (highest priority):
    # canonical forms we know, with unit disambiguation for mass
    exact_map = {
        "temperatur": "temperature",
        "temperature": "temperature",
        "zeit": "time",
        "time": "time",
        "schrittzeit": "step_time",
        "step time": "step_time",
        "masse": None,   # disambiguated by unit below
        "weight": None,
        "mass": None,
        "abl. masse": "dtg",
        "deriv. weight": "dtg",
        "1/temperatur": None,   # reciprocal — never temperature
        "zieltemperatur": None,  # set point — never the measured temp
        "temperaturdifferenz": None,  # DTA — never the measured temp
    }
    exact = exact_map.get(display)
    if display.startswith("1/"):
        return None  # reciprocal columns are never raw signals
    if display in ("temperaturdifferenz", "temperature difference", "dta"):
        return None  # DTA, not the measured temperature
    if display in ("zieltemperatur", "target temperature", "set point temperature"):
        return None  # set point, not measured
    if exact == "mass_pct" or (display in ("masse", "weight", "mass")):
        # Mass: unit decides % vs mg
        if unit and "%" in unit:
            return "mass_pct"
        if unit and ("mg" in unit or "µg" in unit):
            return "mass_mg"
        return None
    if exact in ("temperature", "time", "step_time"):
        return exact
    # Substring fallback (only for clear, unambiguous role terms)
    for role, (terms, unit_suffix) in _ROLE_TERMS.items():
        if any(t in display for t in terms):
            if unit and unit_suffix and unit_suffix not in unit:
                continue
            # never let a substring match steal temperature/time from an
            # exact '1/Temperatur' / 'Temperaturdifferenz' sibling
            if role in ("temperature", "time") and display.startswith(("1/", "differenz", "difference")):
                continue
            return role
    return None


class TriosJsonError(Exception):
    """Raised when a TRIOS JSON cannot be read or has no usable signals."""


def _read_rows_columns(data: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Pull Rows + ColumnHeaders from the first usable DataSet.

    Preference: Results.Processed (analyzed/smoothed), fall back to
    Results.Original (raw). Returns (rows, column_headers).
    """
    results = data.get("Results") or {}
    for ds_name in ("Processed", "Original"):
        ds = results.get(ds_name) or {}
        if not isinstance(ds, dict):
            continue
        rows = ds.get("Rows")
        headers = ds.get("ColumnHeaders") or {}
        if isinstance(rows, list) and rows and isinstance(headers, dict):
            return rows, headers
    raise TriosJsonError("No usable Results.Processed/Original Rows found")


def extract_trios_signals(data: Dict[str, Any], max_points: int = 4000) -> Dict[str, Any]:
    """Extract downsampled numeric signals + metadata from parsed TRIOS JSON.

    Args:
        data: The parsed JSON (dict from json.load).
        max_points: Cap for the returned signal arrays (downsampling).
            Original JSON stays intact as an upload file — this only limits
            what is embedded into the NOMAD entry.

    Returns dict with:
        meta: {sample_name, pan_type, pan_number, sample_mass_mg,
               operator, procedure_name, start_time, source_step_count, row_count}
        signals: {temperature[], time[], mass_pct[], mass_mg[], dtg[]} (downsampled)
        columns: canonical keys actually used
    """
    if not isinstance(data, dict):
        raise TriosJsonError("JSON root is not an object")

    rows, headers = _read_rows_columns(data)

    # Classify columns once — pick ONE column per role (priority order so an
    # exact 'Temperatur_°C' wins over '1/Temperatur' / 'Zieltemperatur' /
    # 'Temperaturdifferenz'; 'Masse_%' over 'Abl. Masse_% / °C').
    roles: Dict[str, str] = {}
    for key, header in headers.items():
        role = _classify_column(key, header)
        if role and role in SIGNAL_ROLES and role not in roles.values():
            roles[key] = role

    if "temperature" not in roles.values():
        raise TriosJsonError("No temperature column found in TRIOS JSON")
    # Prefer temperature over its look-alikes by keeping the FIRST exact match
    # (headers order in the file puts 'Temperatur_°C' before '1/Temperatur')
    role_to_key = {role: key for key, role in roles.items()}
    # Collect arrays (only numeric) from the chosen columns
    arrays: Dict[str, List[float]] = {role: [] for role in SIGNAL_ROLES}
    for row in rows:
        if not isinstance(row, dict):
            continue
        for role, key in role_to_key.items():
            val = row.get(key)
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                arrays[role].append(float(val))
            else:
                arrays[role].append(np.nan)

    n = len(arrays["temperature"])
    if n == 0:
        raise TriosJsonError("No numeric rows in TRIOS JSON")

    # Downsample by uniform stride to max_points (keep first/last)
    def _down(arr: List[float]) -> List[float]:
        arr_np = np.asarray(arr, dtype=float)
        if len(arr_np) <= max_points:
            return arr_np.tolist()
        idx = np.linspace(0, len(arr_np) - 1, max_points).round().astype(int)
        return arr_np[idx].tolist()

    signals = {role: _down(arrays[role]) for role in SIGNAL_ROLES if arrays[role]}

    # Metadata
    sample = data.get("Sample") or {}
    procedure = data.get("Procedure") or {}
    mass = sample.get("Mass") or {}
    mass_val = mass.get("Value") if isinstance(mass, dict) else None
    meta = {
        "sample_name": sample.get("Name"),
        "pan_type": sample.get("PanType"),
        "pan_number": sample.get("PanNumber"),
        "sample_mass_mg": mass_val,
        "operator": (data.get("Operators") or [{}])[0].get("Name") if data.get("Operators") else None,
        "procedure_name": procedure.get("Name"),
        "start_time": data.get("StartTime"),
        "step_count": len(procedure.get("Steps") or []),
        "row_count": n,
    }
    return {"meta": meta, "signals": signals, "columns": list(roles.keys())}


def extract_sample_name(data: Dict[str, Any]) -> Optional[str]:
    """Quick accessor: sample name (used by the operator app for mapping)."""
    try:
        sample = data.get("Sample") or {}
        return sample.get("Name")
    except Exception:
        return None


def read_trios_json_file(path: str, max_points: int = 4000) -> Dict[str, Any]:
    """Read a TRIOS JSON file from disk and extract signals (streaming-friendly).

    Uses a memory-bounded JSON read: loads the full file (a 134 MB export
    loads in ~2-3s and ~300 MB RAM with stdlib json) — acceptable for the
    operator app, but the NOMAD worker should call extract_trios_signals on
    already-loaded data when possible.
    """
    with open(path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    return extract_trios_signals(data, max_points=max_points)


def _lttb_downsample(x: List[float], y: List[float], max_points: int) -> Tuple[List[float], List[float]]:
    """Largest-Triangle-Three-Buckets downsampling (keeps shape).

    Falls back to uniform stride if max_points >= len(x).
    """
    x_np = np.asarray(x, dtype=float)
    y_np = np.asarray(y, dtype=float)
    n = len(x_np)
    if n <= max_points or max_points < 3:
        return x_np.tolist(), y_np.tolist()
    idx = _lttb_indices(y_np, max_points)
    return x_np[idx].tolist(), y_np[idx].tolist()


def _lttb_indices(y: np.ndarray, m: int) -> np.ndarray:
    """LTTB index selection on a 1D array (n >= m >= 3)."""
    n = len(y)
    idx = np.empty(m, dtype=np.int64)
    idx[0], idx[-1] = 0, n - 1
    # Bucket size
    every = (n - 2) / (m - 2)
    a = 0
    for i in range(1, m - 1):
        # Bucket range for this step
        a_floor = int(np.floor((i - 1) * every)) + 1
        a_ceil = int(np.floor(i * every)) + 1
        a_ceil = min(a_ceil, n - 1)
        if a_ceil <= a:
            a_ceil = a + 1
        # Average of the NEXT bucket
        na_floor = int(np.floor(i * every)) + 1
        na_ceil = int(np.floor((i + 1) * every)) + 1
        na_ceil = min(na_ceil, n - 1)
        if na_ceil <= na_floor:
            na_ceil = na_floor + 1
        avg_x = np.mean(np.arange(na_floor, na_ceil))
        avg_y = np.mean(y[na_floor:na_ceil])
        # Pick point in current bucket with max triangle area
        a = _argmax_area(y, a_floor, a_ceil, idx[i - 1], avg_x, avg_y)
        idx[i] = a
    return idx


def _argmax_area(y: np.ndarray, lo: int, hi: int, prev_idx: int, avg_x: float, avg_y: float) -> int:
    best_i, best_area = lo, -1.0
    px, py = float(prev_idx), float(y[prev_idx])
    for i in range(lo, hi):
        area = abs((px - avg_x) * (y[i] - py) - (px - float(i)) * (avg_y - py))
        if area > best_area:
            best_area, best_i = area, i
    return best_i
