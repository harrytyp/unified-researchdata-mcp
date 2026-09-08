"""Normalizer for MockInstrumentRun. Generates mock TGA data and populates
results when the user toggles run_now = True in the NOMAD GUI.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

# Import mock generation
from instrument_data.mock_run import generate_and_write
from instrument_data.parser import detect_format, parse_file
from instrument_data.elabftw_client import ElabftwClient


def run_mock_instrument(entry: Any, archive: Any, logger: Any) -> None:
    """Called by MockInstrumentRun.normalize(). Generates mock data, parses
    it, computes results, and populates the entry's results section.

    If ELABFTW_API_KEY is set, also pushes results to elabFTW.
    """
    cfg = entry.config
    if not cfg:
        logger.warning("MockInstrumentRun: no config")
        return

    logger.info("Mock instrument run starting...")
    entry.run_now = False

    # Ensure results section exists
    if not entry.results:
        from instrument_data.schema import MockRunResults
        entry.results = MockRunResults()
    results = entry.results
    results.run_status = "running"

    # Determine output directory
    outdir = os.environ.get(
        "MOCK_EXPORT_DIR",
        "/home/debian/instrument-exports/",
    )

    # Resolve experiment ID from elabFTW if we have an API key
    experiment_id = None
    api_key = os.environ.get("ELABFTW_API_KEY", "")
    api_url = os.environ.get(
        "ELABFTW_API_URL",
        "https://elntest.ub.tum.de/api/v2",
    )
    team = int(os.environ.get("ELABFTW_TEAM", "29"))

    try:
        # Step 1: Generate mock TGA data
        gen_result = generate_and_write(
            outdir=outdir,
            sample_name=cfg.sample_name or "Polymer-X",
            sample_mass_mg=cfg.sample_mass_mg or 12.5,
            temp_start=cfg.temperature_start or 30.0,
            temp_end=cfg.temperature_end or 1000.0,
            heating_rate=cfg.heating_rate or 10.0,
            gas=cfg.gas_atmosphere or "N2",
            flow_rate=cfg.gas_flow_rate or 50.0,
            crucible=cfg.crucible_type or "Alumina",
            operator=cfg.operator or "Demo",
            experiment_id=None,
            seed=abs(hash(datetime.now().isoformat())) % (2**31),
        )

        filepath = gen_result["filepath"]
        results.generated_file = filepath
        results.signal_points = gen_result.get("signal_count", 0)
        results.channels = ", ".join(gen_result.get("channels", []))
        logger.info(f"Mock data written to {filepath}")

        # Step 2: Parse the file
        fmt = detect_format(filepath)
        if not fmt:
            results.run_status = "error"
            results.run_message = "Could not detect instrument format"
            return

        parsed = parse_file(filepath)
        signals = parsed.get("signals", {})
        metadata = parsed.get("metadata", {})

        # Step 3: Compute results via instrument_ingest logic
        from scripts.instrument_ingest import FileProcessor, Config
        processor = FileProcessor(config=Config(), elab=None)

        computed = processor._compute_results(fmt, signals, metadata)

        # Step 4: Populate results
        results.run_status = "completed"
        results.run_message = (
            f"Generated {results.signal_points} data points "
            f"across {results.channels}. "
            f"File: {os.path.basename(filepath)}"
        )

        if computed.get("tg_glass_transition"):
            results.computed_tg = computed["tg_glass_transition"]
        if computed.get("residue_mass_pct"):
            results.computed_residue = computed["residue_mass_pct"]
        if computed.get("onset_temperature"):
            results.computed_onset = computed["onset_temperature"]
        if computed.get("steps"):
            results.computed_steps = json.dumps(computed["steps"])

        # Step 5: Push to elabFTW if API key is available
        if api_key:
            try:
                _push_to_elabftw(
                    entry=entry,
                    results_data=results,
                    computed=computed,
                    sample_name=cfg.sample_name or "MockSample",
                    api_key=api_key,
                    api_url=api_url,
                    team=team,
                    logger=logger,
                    archive=archive,
                )
            except Exception as e:
                logger.warning(f"elabFTW push failed (non-fatal): {e}")

        logger.info("Mock instrument run completed successfully")

    except Exception as e:
        results.run_status = "error"
        results.run_message = f"Error: {e}"
        logger.error(f"Mock instrument run failed: {e}")


def _push_to_elabftw(
    entry: Any,
    results_data: Any,
    computed: Dict[str, Any],
    sample_name: str,
    api_key: str,
    api_url: str,
    team: int,
    logger: Any,
    archive: Any = None,
) -> None:
    """Push mock results to elabFTW. Creates an experiment if none exists."""
    client = ElabftwClient(
        api_url=api_url,
        api_key=api_key,
        team=team,
    )

    # Get archive metadata for the NOMAD URL
    metadata = archive.metadata if hasattr(archive, 'metadata') else None
    entry_id = metadata.entry_id if metadata else None
    upload_id = metadata.upload_id if metadata else None

    # Create experiment in elabFTW
    title = entry.title or f"Mock TGA: {sample_name}"
    exp = client.create_experiment(
        title=title,
        body=f"<p>Mock instrument run from NOMAD. Generated: {datetime.now().isoformat()}</p>",
        tags=["MOCK", "TGA", "auto-generated"],
    )
    if exp:
        exp_id = exp.get("id")
        results_data.elabftw_experiment_id = str(exp_id)

        # Push computed results
        nomad_url = (
            f"https://researchmcp.duckdns.org/nomad-oasis/gui/user/uploads/entry/"
            f"{upload_id}/{entry_id}"
            if upload_id and entry_id
            else None
        )

        client.push_tga_results(
            experiment_id=exp_id,
            sample_name=sample_name,
            signals={},
            computed=computed,
            nomad_url=nomad_url or "",
        )
        logger.info(f"Results pushed to elabFTW experiment {exp_id}")
