"""Read what a request actually contains: parameters, curves, results.

Where this reads from, and why not from the API: the entry record returned by
`/entries/query` is not usable here - on a real processed upload it still said
"process failed with exception" while the upload reported SUCCESS and the
results were on disk (verified 2026-09-16). The generated entry archive is not
reachable through the raw-file route either (it only serves uploaded files), so
the archive is read from the shared staging volume, the same way the E2E test
verifies a run.

Permissions stay with the API: the caller only ever asks for upload ids that the
API returned for *that user's* token, and the read follows that decision. The
filesystem itself has no per-user check, so this module must never be given an
upload id from user input.

The archive is msgpack and nests the payload; everything is flattened to dotted
paths so a field can be picked by name (`result_td5`, `sample.sample_name`, ...)
without depending on the envelope structure.
"""
from __future__ import annotations

import glob
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("tga.entry")

STAGING_ROOT = os.environ.get("NOMAD_STAGING_ROOT", "/app/.volumes/fs/staging")

# Curve arrays we can use for a figure or a CSV, in the order they are written.
SIGNAL_KEYS = ("result_time_signal", "result_temperature_signal",
               "result_mass_mg_signal", "result_mass_pct_signal",
               "result_dtg_signal", "result_dtg_cleaned_signal")


def staging_dir(upload_id: str) -> Optional[str]:
    """The staging folder of an upload, matched by its id."""
    if not upload_id:
        return None
    matches = sorted(glob.glob(os.path.join(STAGING_ROOT, "*", f"*{upload_id}*")))
    return matches[-1] if matches else None


def archive_paths(upload_id: str) -> List[str]:
    directory = staging_dir(upload_id)
    if not directory:
        return []
    return sorted(glob.glob(os.path.join(directory, "archive", "*.msg")),
                  key=os.path.getmtime)


def _unwrap(value: Any) -> Any:
    """NOMAD may store a quantity as {'value': .., 'unit': ..} - keep the number."""
    if isinstance(value, dict) and "value" in value:
        return value.get("value")
    return value


def _looks_like_id(key: str) -> bool:
    """A NOMAD entry id used as a path segment (`<entry_id>.result_td5`).

    The archive nests the payload under the entry id, which is of no use to a
    caller looking for `result_td5` - so such a segment is skipped while
    flattening.
    """
    return len(key) >= 20 and all(ch.isalnum() or ch in "-_" for ch in key)


# Envelope branches that only clutter the field list.
_SKIP_BRANCHES = ("processing_logs", "figures", "files", "sections", "text_search_contents")


def _flatten(obj: Any, prefix: str, out: Dict[str, Any], depth: int = 0) -> None:
    """Collect leaf values under dotted paths, ignoring the envelope wrappers.

    The archive is a stream of envelope dicts; the payload sits under 'data' and
    under the entry id. Both wrapping levels add nothing, so the innermost keys
    are what a caller searches for ('result_td5', 'sample.sample_name').
    """
    if depth > 12:
        return
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in _SKIP_BRANCHES:
                continue
            if key in ("data", "archive", "entry", "results", "metadata") and isinstance(value, dict):
                _flatten(value, prefix, out, depth + 1)
            elif isinstance(value, dict) and not isinstance(value, (str, bytes)):
                _flatten(value, prefix if _looks_like_id(key) else f"{prefix}{key}.", out, depth + 1)
            elif isinstance(value, list):
                # Lists are kept whole: the signal arrays (thousands of numbers)
                # would otherwise explode into one key per sample, and the
                # program segments are read as a list by the caller.
                out[f"{prefix}{key}"] = [_unwrap(item) for item in value]
            else:
                out[f"{prefix}{key}"] = _unwrap(value)
    elif isinstance(obj, list):
        for value in obj:
            if isinstance(value, (dict, list)):
                _flatten(value, prefix, out, depth + 1)


def read_fields(upload_id: str) -> Dict[str, Any]:
    """All fields of the newest processed entry of an upload ({} if none yet).

    Later archives win, and the newest file is read last: a re-processing run
    overwrites values, so the last write is the valid one.
    """
    paths = archive_paths(upload_id)
    if not paths:
        return {}
    try:
        import msgpack
    except Exception:                              # noqa: BLE001
        log.warning("msgpack not available, cannot read the entry archive")
        return {}
    fields: Dict[str, Any] = {}
    for path in paths:
        try:
            with open(path, "rb") as handle:
                unpacker = msgpack.Unpacker(raw=False, strict_map_key=False)
                unpacker.feed(handle.read())
                for obj in unpacker:
                    _flatten(obj, "", fields)
        except Exception as error:                 # noqa: BLE001
            log.warning("archive %s not readable: %s", path, error)
    return fields


def figure_count(fields: Dict[str, Any]) -> int:
    """How many figures the entry carries (checked on the raw objects)."""
    return sum(1 for key in fields if ".figure.figure" in key or key.startswith("figures."))


def signals(fields: Dict[str, Any]) -> Dict[str, List[float]]:
    """The curve arrays, keyed the way the ELN package expects them."""
    mapping = {
        "time": "result_time_signal",
        "temperature": "result_temperature_signal",
        "mass_mg": "result_mass_mg_signal",
        "mass_pct": "result_mass_pct_signal",
        "dtg": "result_dtg_signal",
        "dtg_cleaned": "result_dtg_cleaned_signal",
    }
    out: Dict[str, List[float]] = {}
    for name, key in mapping.items():
        value = fields.get(key)
        if isinstance(value, list) and value:
            out[name] = [v for v in value if isinstance(v, (int, float))]
    return out


def _fmt(value: Any, unit: str = "", digits: int = 2) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        text = f"{value:.{digits}f}"
    else:
        text = str(value)
    return f"{text} {unit}".strip()


def results(fields: Dict[str, Any]) -> Dict[str, str]:
    """Result values as the mails and the ELN package show them."""
    td5 = fields.get("result_td5")
    td10 = fields.get("result_td10")
    residue = fields.get("result_residue")
    mass = fields.get("result_sample_mass_mg")
    pan_type = fields.get("result_pan_type") or fields.get("pan_type")
    pan_number = fields.get("result_pan_number") or fields.get("pan_number")
    sample_name = fields.get("result_sample_name") or fields.get("sample.sample_name")
    procedure = fields.get("result_procedure_name")

    mass_loss = ""
    if isinstance(residue, (int, float)):
        mass_loss = _fmt(100.0 - float(residue), "%", 1)
    pan = ""
    if pan_type or pan_number:
        pan = f"{pan_type or '?'}" + (f" #{pan_number}" if pan_number else "")

    values = {
        "mass_loss": mass_loss,
        "td5": _fmt(td5, "°C", 1),
        "td10": _fmt(td10, "°C", 1),
        "residue": _fmt(residue, "%", 1),
        "sample_mass": _fmt(mass, "mg", 3),
        "pan": pan,
        "sample_name": sample_name or "",
        "procedure": procedure or "",
    }
    return {key: value for key, value in values.items() if value}


# The procedure is a list of typed steps (RampSegment, IsothermalSegment,
# MassFlowSegment, BalanceFlowSegment); the type sits in the item's m_def and
# each type carries its own fields. Rendering them by type is what makes the
# program readable in a mail - a bare index tells nobody anything.
_SEGMENT_KINDS = {
    "RampSegment": "ramp",
    "IsothermalSegment": "hold",
    "MassFlowSegment": "sample_flow",
    "BalanceFlowSegment": "balance_flow",
}


def _segments(raw_segments: Any) -> List[Dict[str, Any]]:
    """The temperature program as typed steps, in order."""
    segments: List[Dict[str, Any]] = []
    for raw in raw_segments or []:
        if not isinstance(raw, dict):
            continue
        kind = "ramp"
        for name, mapped in _SEGMENT_KINDS.items():
            if str(raw.get("m_def", "")).endswith(name):
                kind = mapped
                break
        segments.append({
            "kind": kind,
            "end_temp": _unwrap(raw.get("end_temp")),
            "rate": _unwrap(raw.get("rate")),
            "duration_min": _unwrap(raw.get("duration_min")),
            "flow_rate": _unwrap(raw.get("flow_rate")),
        })
    return segments


def _plain(value: Any) -> str:
    """A number for a sentence: no trailing ".0", no unit (the unit is in the text)."""
    text = _fmt(value, "", 1).strip()
    return text[:-2] if text.endswith(".0") else text


def segment_lines(segments: Any) -> List[str]:
    """One readable line per program step (English, no dashes as punctuation)."""
    lines: List[str] = []
    for index, segment in enumerate(segments or [], start=1):
        kind = segment.get("kind") or "ramp"
        if kind == "ramp":
            target = _plain(segment.get("end_temp"))
            rate = _plain(segment.get("rate"))
            text = f"Ramp to {target} C"
            if rate:
                text += f" at {rate} C/min"
        elif kind == "hold":
            text = f"Hold for {_plain(segment.get('duration_min'))} min"
        elif kind == "sample_flow":
            text = f"Sample purge flow {_plain(segment.get('flow_rate'))} mL/min"
        else:
            text = f"Balance purge flow {_plain(segment.get('flow_rate'))} mL/min"
        lines.append(f"{index}. {text}")
    return lines


def parameters(fields: Dict[str, Any]) -> Dict[str, Any]:
    """What was requested, in the words the form used."""
    segments = _segments(fields.get("temperature_segments"))

    # Die Laufzeit schaetzt das Formular; im Archiv steht sie nicht. Also aus dem
    # Programm ableiten (Rampen plus Haltezeiten) - sonst bleibt in der Mail eine
    # leere Zeile, wo der Nutzer seine eigene Schaetzung erwartet.
    ramp_minutes = 0.0
    hold_minutes = 0.0
    previous = fields.get("start_temp")
    for segment in segments:
        if segment["kind"] == "ramp":
            rate = segment.get("rate")
            end = segment.get("end_temp")
            begin = previous if isinstance(previous, (int, float)) else fields.get("start_temp")
            if (isinstance(rate, (int, float)) and rate
                    and isinstance(end, (int, float)) and isinstance(begin, (int, float))):
                ramp_minutes += max(end - begin, 0.0) / rate
            if isinstance(end, (int, float)):
                previous = end
        elif segment["kind"] == "hold":
            if isinstance(segment.get("duration_min"), (int, float)):
                hold_minutes += float(segment["duration_min"])

    gas = fields.get("gas_atmosphere") or fields.get("atmosphere")
    flows = []
    if fields.get("gas_flow_rate"):
        flows.append(f"{_fmt(fields.get('gas_flow_rate'), 'mL/min', 1)} sample gas")
    if fields.get("balance_flow_rate"):
        flows.append(f"{_fmt(fields.get('balance_flow_rate'), 'mL/min', 1)} balance gas")
    ms = fields.get("ms_coupling")
    runtime = fields.get("estimated_runtime_h")
    if not isinstance(runtime, (int, float)) and (ramp_minutes or hold_minutes):
        runtime = (ramp_minutes + hold_minutes) / 60.0
    return {
        "atmosphere": gas or "",
        "gas_flows": ", ".join(flows),
        "ms_coupling": ("coupled" if ms else "not coupled") if ms is not None else "",
        "sample_mass": _fmt(fields.get("sample.sample_mass"), "mg", 3),
        "runtime": _fmt(runtime, "h", 1),
        "segments": segments,
    }


def request_summary(upload_id: str) -> Dict[str, Any]:
    """Everything the notifications, the ELN package and the page need.

    One read, one dict: the caller does not have to know how the archive is
    nested, and a missing archive (not measured yet) yields empty blocks instead
    of an exception.
    """
    fields = read_fields(upload_id)
    res = results(fields)
    return {
        "fields": fields,
        "results": res,
        "parameters": parameters(fields),
        "signals": signals(fields),
        "sample_name": res.get("sample_name") or "",
        "requester": fields.get("requester_email") or "",
        "operator": fields.get("operator") or fields.get("sample.operator") or "",
        "comment": fields.get("comments") or "",
        "measured": bool(res),
    }


def dtg_settings(fields: Dict[str, Any]) -> Tuple[str, str]:
    """The cleaning values that produced the plotted curve (for the README)."""
    window = _fmt(fields.get("result_dtg_clean_window_c"), "°C", 2)
    delta = _fmt(fields.get("result_dtg_clean_delta"), "", 4)
    return window, delta
