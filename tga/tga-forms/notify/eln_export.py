"""The download package for the ELN.

Not every ELN can be reached by API, and sometimes somebody simply wants the
files. Both cases get the same ZIP: the result values, the measured curves, the
DTG figure and a README that explains in one page what the files are, where they
came from and which values are computed rather than measured.

Written as plain text and CSV on purpose - it has to open in Excel, in an ELN
import dialog and in a text editor years from now.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import zipfile
from typing import Any, Dict, Iterable, List, Optional

log = logging.getLogger("tga.eln")

README_TEMPLATE = """TGA measurement {code} - {sample}
{underline}

Source
------
Exported from the TGA request system of the Chair of Materials Science
(TUM School of Engineering and Design).
NOMAD entry: {entry_url}

Requester : {requester}
Measured  : {measured_on}
Operator  : {operator}
Exported  : {exported_at}

Files
-----
{code}_results.csv     result values, one row per value (name, value, unit)
{code}_curves.csv      measured curves: time, temperature, mass, DTG
{code}_metadata.json   parameters, program segments and links, for import
{code}_dtg.png         the DTG curve as a figure
README.txt             this file

How the values are obtained
---------------------------
Every value is computed by the NOMAD instrument-data plugin from the raw TRIOS
export, not copied from a report:
  mass loss    from the mass signal over the measurement
  Td5 / Td10   temperature at 5% / 10% mass loss (onset)
  residue      remaining mass at the end of the program
  DTG          derivative of the mass, in %/min, smoothed and cleaned with the
               lab's procedure (forward and backward exponential moving
               average; points far off the smoothed curve are dropped as noise
               and the gaps interpolated). Window and threshold are derived from
               the curve itself, this measurement used {dtg_window} and
               {dtg_delta}.

Results
-------
{results_block}

Contact
-------
{contacts}
"""


def _contacts_text(contacts: Optional[Dict[str, str]]) -> str:
    contacts = contacts or {}
    lines = []
    if contacts.get("pedro"):
        lines.append(f"Pedro Braun <{contacts['pedro']}>")
    if contacts.get("luca"):
        lines.append(f"Luca Reichert <{contacts['luca']}>")
    return "\n".join(lines) or "(not configured)"


def _csv(rows: Iterable[Iterable[Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue()


def results_csv(results: Dict[str, Any]) -> str:
    """One row per value: name, value, unit. Units stay separate so the value
    column stays numeric for whoever imports it."""
    rows: List[List[Any]] = [["name", "value", "unit"]]
    for label, value in (results or {}).items():
        if isinstance(value, dict):
            rows.append([label, value.get("value", ""), value.get("unit", "")])
        else:
            rows.append([label, value, ""])
    return _csv(rows)


def curves_csv(signals: Dict[str, Any]) -> str:
    """The measured curves, one column per signal, empty cells kept empty."""
    signals = signals or {}
    order = [name for name in ("time", "temperature", "mass_mg", "mass_pct",
                               "dtg", "dtg_cleaned") if signals.get(name)]
    if not order:
        return ""
    length = max(len(signals[name]) for name in order)
    rows: List[List[Any]] = [order]
    for index in range(length):
        row = []
        for name in order:
            values = signals[name]
            value = values[index] if index < len(values) else ""
            row.append(value)
        rows.append(row)
    return _csv(rows)


def dtg_figure(signals: Dict[str, Any], title: str) -> Optional[bytes]:
    """The DTG curve as PNG: raw behind, cleaned in front.

    Returns None when matplotlib is unavailable - the package stays usable, the
    README just says there is no figure.
    """
    temperature = (signals or {}).get("temperature") or []
    cleaned = (signals or {}).get("dtg_cleaned") or []
    raw = (signals or {}).get("dtg") or []
    if not temperature or not cleaned:
        return None
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:                              # noqa: BLE001 - optional dependency
        log.warning("matplotlib not available, no figure in the package")
        return None

    figure, axes = plt.subplots(figsize=(10, 5))
    if raw and len(raw) == len(temperature):
        axes.plot(temperature, raw, "-", lw=0.7, alpha=0.35, color="tab:blue",
                  label="DTG (raw)")
    axes.plot(temperature, cleaned, "-", lw=1.6, color="black", label="DTG (cleaned)")
    axes.set_xlabel("Temperature (°C)")
    axes.set_ylabel("DTG (%/min)")
    axes.set_title(title)
    axes.grid(True, alpha=0.3)
    axes.legend()
    figure.tight_layout()
    buffer = io.BytesIO()
    figure.savefig(buffer, format="png", dpi=150)
    plt.close(figure)
    return buffer.getvalue()


def readme_text(code: str, sample_name: str, ctx: Dict[str, Any],
                results: Dict[str, Any], has_figure: bool) -> str:
    title = f"TGA measurement {code} - {sample_name}"
    # Die wichtigsten Werte stehen auch im README: wer das ZIP nur oeffnet, soll
    # die Zahlen sehen, ohne erst die CSV zu laden.
    highlights = [name for name in ("mass_loss", "td5", "td10", "residue",
                                    "sample_mass", "pan") if results.get(name)]
    if highlights:
        width = max(len(name.replace("_", " ")) for name in highlights)
        results_block = "\n".join(
            f"  {name.replace('_', ' ').ljust(width)} : {results[name]}"
            for name in highlights)
    else:
        results_block = "  (no values yet, see the NOMAD entry)"
    text = README_TEMPLATE.format(
        code=code or "sample",
        sample=sample_name or "(no name)",
        underline="-" * len(title),
        entry_url=ctx.get("entry_url", "") or "(not linked)",
        requester=ctx.get("requester", "") or "(unknown)",
        measured_on=ctx.get("measured_on", "") or "(see the NOMAD entry)",
        operator=ctx.get("operator", "") or "(unknown)",
        exported_at=ctx.get("exported_at", ""),
        contacts=_contacts_text(ctx.get("contacts")),
        results_block=results_block,
        dtg_window=ctx.get("dtg_window", "") or "(see the entry)",
        dtg_delta=ctx.get("dtg_delta", "") or "(see the entry)",
    )
    if not has_figure:
        text = text.replace("DTG curve as a figure", "DTG curve as a figure (not included)")
    return text


def build_package(*, code: str, sample_name: str, results: Dict[str, Any],
                  signals: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None,
                  include_figure: bool = True) -> bytes:
    """Build the ZIP. Empty sections are left out rather than shipped blank."""
    ctx = dict(ctx or {})
    stem = (code or "sample").replace("/", "-").strip() or "sample"
    figure = dtg_figure(signals, f"TGA {stem} - {sample_name}") if include_figure else None

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{stem}_results.csv", results_csv(results))
        curves = curves_csv(signals)
        if curves:
            zf.writestr(f"{stem}_curves.csv", curves)
        if figure:
            zf.writestr(f"{stem}_dtg.png", figure)
        zf.writestr(f"{stem}_metadata.json",
                    json.dumps({"sample_code": code, "sample_name": sample_name,
                                "results": results, "context": {
                                    k: v for k, v in ctx.items() if k != "api_key"}},
                               ensure_ascii=False, indent=2, sort_keys=True))
        zf.writestr("README.txt", readme_text(stem, sample_name, ctx, results,
                                              bool(figure)))
    return archive.getvalue()


def package_filename(code: str, sample_name: str = "") -> str:
    stem = (code or "sample").replace("/", "-").strip() or "sample"
    sample = "".join(ch if ch.isalnum() or ch in "-_" else "_"
                     for ch in (sample_name or ""))[:40]
    return f"TGA_{stem}_{sample}.zip" if sample else f"TGA_{stem}.zip"
