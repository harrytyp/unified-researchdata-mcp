"""NOMAD parser for TGA CSV/TXT measurement files.

Registered as a NOMAD plugin, triggered on upload of .txt/.csv files
that contain TGA instrument data. Uses the shared processor module
for parsing and computation.

Entry point name: parsers/tga
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import IO

from nomad.datamodel import EntryArchive
from nomad.datamodel.data import EntryData
from nomad.metainfo import MSection
from nomad.parsing import MatchingParser
from nomad.datamodel.metainfo.annotations import ELNAnnotation

from instrument_data.parser import detect_format, parse_file, extract_tga_metadata
from instrument_data.processor import compute_tga, generate_plot


# TGA column headers that indicate this is TGA data
TGA_HEADER_INDICATORS = [
    "value/mg", "temp./c", "delta/c/min", "sample weight/mg",
    "weight/mg", "temperature/°c", "sample weight",
    "time/min", "time/s", "index",
]

# Strong signal keywords
TGA_KEYWORDS = [
    "tga", "thermogravimetric",
    "instrument_type", "instrument_name",
]


class TgaParser(MatchingParser):
    def __init__(self):
        super().__init__(
            name='parsers/tga',
            code_name='TGA Parser',
            domain=None,
            mainfile_mime_re='.*',
            mainfile_name_re=r'.*\.(txt|csv|dat|xlsx|xls)$',
            level=0,
        )

    def is_mainfile(
        self,
        filename: str,
        mime: str,
        buffer: bytes,
        decoded_buffer: str,
        compression: str | None = None,
    ) -> bool | list[str]:
        # Skip empty files
        import sys as _sys; print(f"[TGAParser] is_mainfile called", file=_sys.stderr, flush=True)
        if not decoded_buffer:
            # Accept xlsx files by extension and MIME type
            if filename.lower().endswith((".xlsx", ".xls")):
                return True
            if "spreadsheet" in (mime or ""):
                return True
            return False

        head = decoded_buffer[:4096].lower()

        # Strong signal: file explicitly says it's TGA
        if any(kw in head for kw in TGA_KEYWORDS):
            return True

        # Check for TGA column headers (common in CSV/TXT exports)
        lines = head.split("\n")
        header_line = lines[0] if lines else ""
        tga_header_hits = sum(1 for ind in TGA_HEADER_INDICATORS if ind in header_line)
        if tga_header_hits >= 3:
            return True

        # Confirm with the format detector from parser module
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write(decoded_buffer)
            tmp_path = f.name
        try:
            fmt = detect_format(tmp_path)
            return fmt == 'tga'
        except Exception:
            # If detect_format fails, accept files that have at least
            # 2 TGA-like header indicators (broad match)
            return tga_header_hits >= 2
        finally:
            os.unlink(tmp_path)

    def parse(
        self,
        mainfile: str,
        archive: EntryArchive,
        logger=None,
        child_archives: dict[str, EntryArchive] | None = None,
    ) -> None:
        logger.info(f'TGA Parser processing {mainfile}')

        # 1. Parse the raw file
        parsed = parse_file(mainfile)
        signals = parsed.get('signals', {})
        metadata = parsed.get('metadata', {})
        norm = extract_tga_metadata(metadata)

        # 2. Compute results
        computed = compute_tga(signals, metadata)

        # 3. Populate the entry archive
        from instrument_data.schema import TgaMeasurement, TgaResults, TgaStep, InstrumentSample

        # Create the measurement section
        tga = TgaMeasurement()
        # tga.m_def is set via the EntryArchive entry_type instead

        # Sample info
        tga.sample = InstrumentSample()
        tga.sample.sample_name = norm.get('sample_name', parsed.get('metadata', {}).get('sample_name', Path(mainfile).stem))
        if norm.get('sample_mass_mg'):
            tga.sample.sample_mass = norm['sample_mass_mg']
        tga.sample.operator = norm.get('operator', '')
        tga.original_filename = Path(mainfile).name

        # Method params
        tga.procedure_name = norm.get('method_name', '')
        if norm.get('heating_rate'):
            rate = norm.get('heating_rate', '')
            tend = norm.get('temperature_end', '')
            tga.procedure_segments = f'{rate} K/min to {tend} °C'
        tga.gas_atmosphere = norm.get('gas_atmosphere', '')
        tga.crucible_type = norm.get('pan_type', '')

        # Instrument info
        tga.instrument_name = metadata.get('instrument_name', '')
        tga.instrument_type = metadata.get('instrument_type', '')

        # Signal data (wrap in dict so JSON type accepts lists)
        if 'temperature' in signals:
            tga.temperature_signal = {'values': signals['temperature']}
        weight_key = 'weight' if 'weight' in signals else ('mass' if 'mass' in signals else None)
        if weight_key:
            tga.weight_signal = {'values': signals[weight_key]}
        if 'dta' in signals:
            tga.dta_signal = {'values': signals['dta']}

        # Add elabFTW reference if available
        elab_item_id = None
        import re as _re_elab
        _m = _re_elab.search(r'item([0-9]+)', Path(mainfile).stem)
        if _m:
            elab_item_id = _m.group(1)
            elab_url = f'https://elntest.ub.tum.de/database.php?mode=view&id={elab_item_id}'
            # Store elabFTW URL in entry references
            refs = list(archive.metadata.references or [])
            if elab_url not in refs:
                refs.append(elab_url)
                archive.metadata.references = refs
        
        # Computed results
        summary = computed.get('summary', {})
        tga.results = TgaResults()
        if summary.get('onset_temperature_c'):
            tga.results.onset_temperature = summary['onset_temperature_c']
        if summary.get('residue_mass_pct'):
            tga.results.residue_mass_pct = summary['residue_mass_pct']
        if summary.get('mass_loss_5pct'):
            tga.results.mass_loss_5pct = summary['mass_loss_5pct']
        if summary.get('mass_loss_10pct'):
            tga.results.mass_loss_10pct = summary['mass_loss_10pct']

        # Mass loss steps
        steps_data = computed.get('steps', [])
        if steps_data:
            tga.results.steps = []
            for sd in steps_data:
                step = TgaStep()
                step.peak_dtg_temperature = sd.get('peak_temperature_c')
                step.mass_loss_pct = sd.get('mass_loss_pct')
                step.assignment = sd.get('assignment')
                tga.results.steps.append(step)

        # Generate and embed plot as base64
        try:
            plot_png = generate_plot(signals, computed)
            if plot_png:
                import base64
                tga.summary_plot = base64.b64encode(plot_png).decode('ascii')
        except Exception:
            pass

        # Assign to archive
        archive.data = tga
        logger.info(f'TGA parsing complete for {Path(mainfile).name}')
