#!/usr/bin/env python3
"""Instrument Data Ingest: watch folder, parse, push to elabFTW.

Monitors a directory for TRIOS-exported CSV/TXT files, parses them,
matches to elabFTW experiments, and pushes results back.

Two modes:
  1. One-shot: process a single file or all files in a directory
  2. Watch: continuously monitor a directory for new files

Usage:
    # One-shot: process a single file
    python instrument-ingest.py process TGA_PolymerX.csv

    # One-shot: process all files in a directory
    python instrument-ingest.py process /data/tga-exports/

    # Watch mode: monitor directory continuously
    python instrument-ingest.py watch /data/tga-exports/

    # Dry run: show what would be done without writing
    python instrument-ingest.py --dry-run process TGA_PolymerX.csv

Configuration via environment variables:
    ELABFTW_API_URL     elabFTW API base URL (default: https://elntest.ub.tum.de/api/v2)
    ELABFTW_API_KEY     elabFTW API key (required for push-back)
    ELABFTW_TEAM        Team ID (default: 29)
    NOMAD_API_URL       NOMAD Oasis API URL (default: http://localhost:8000/api/v1)
    WATCH_POLL_SECONDS  Watch mode poll interval (default: 60)
    DRY_RUN             Set to "true" for dry-run mode
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import shutil
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Add parent to path for plugin imports
_plugin_dir = Path(__file__).resolve().parent.parent / "plugins"
sys.path.insert(0, str(_plugin_dir))

from instrument_data.parser import (
    parse_file,
    detect_format,
    extract_tga_metadata,
    normalize_mass_unit,
)
from instrument_data.elabftw_client import ElabftwClient

logger = logging.getLogger("instrument-ingest")


# ── Config ───────────────────────────────────────────────────────────────────

class Config:
    def __init__(self):
        self.elabftw_api_url = os.getenv(
            "ELABFTW_API_URL",
            "https://elntest.ub.tum.de/api/v2",
        )
        self.elabftw_api_key = os.getenv("ELABFTW_API_KEY", "")
        self.elabftw_team = int(os.getenv("ELABFTW_TEAM", "29"))
        self.nomad_api_url = os.getenv("NOMAD_API_URL", "http://localhost:8000/api/v1")
        self.watch_poll_seconds = int(os.getenv("WATCH_POLL_SECONDS", "60"))
        self.dry_run = os.getenv("DRY_RUN", "").lower() in ("true", "1", "yes")

        # Directories (relative to processing base)
        self.archive_dir = "processed"
        self.error_dir = "errors"
        self.processing_dir = "processing"

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> "Config":
        cfg = cls()
        if args.dry_run:
            cfg.dry_run = True
        if args.api_key:
            cfg.elabftw_api_key = args.api_key
        if args.api_url:
            cfg.elabftw_api_url = args.api_url
        if args.team:
            cfg.elabftw_team = args.team
        if args.watch_poll:
            cfg.watch_poll_seconds = args.watch_poll
        return cfg


# ── Processing ───────────────────────────────────────────────────────────────

class FileProcessor:
    """Process a single instrument export file."""

    def __init__(self, config: Config, elab: Optional[ElabftwClient] = None):
        self.config = config
        self.elab = elab

    def process(self, filepath: str) -> Dict[str, Any]:
        """Process a single instrument export file.

        Returns processing result with status, metadata, and any errors.
        """
        result: Dict[str, Any] = {
            "file": filepath,
            "status": "pending",
            "errors": [],
            "warnings": [],
            "metadata": {},
            "format": None,
        }

        path = Path(filepath)

        # 1. Validate file
        if not path.exists():
            result["status"] = "error"
            result["errors"].append(f"File not found: {filepath}")
            return result
        if path.suffix.lower() not in (".csv", ".txt"):
            result["status"] = "skipped"
            result["warnings"].append(f"Unsupported extension: {path.suffix}")
            return result

        # 2. Detect format
        fmt = detect_format(str(path))
        result["format"] = fmt
        if not fmt:
            result["status"] = "skipped"
            result["warnings"].append("Could not detect instrument format")
            return result

        logger.info(f"Processing {path.name} (format: {fmt})")

        # 3. Parse file
        try:
            parsed = parse_file(str(path))
        except Exception as e:
            result["status"] = "error"
            result["errors"].append(f"Parse error: {e}")
            return result

        metadata = parsed.get("metadata", {})
        signals = parsed.get("signals", {})
        result["metadata"] = metadata
        result["signal_count"] = {k: len(v) for k, v in signals.items()}

        # 4. Extract normalized metadata
        if fmt == "tga":
            norm_meta = extract_tga_metadata(metadata)
            sample_name = norm_meta.get("sample_name", path.stem)
        else:
            sample_name = metadata.get("sample_name", metadata.get("filename", path.stem))

        result["sample_name"] = sample_name

        # 5. Match to elabFTW experiment
        experiment_id = self._match_experiment(sample_name, metadata, fmt)
        result["experiment_id"] = experiment_id

        # 6. Compute results (format-specific)
        computed = self._compute_results(fmt, signals, metadata)
        result["computed"] = computed

        # 7. Generate plot
        plot_b64 = self._generate_plot(fmt, signals, computed)

        # 8. Push to elabFTW
        if experiment_id and self.elab and not self.config.dry_run:
            # Set Running status before processing
            self.elab.set_running(experiment_id)
            try:
                nomad_url = self._create_nomad_entry(fmt, sample_name, parsed, computed)
                push_ok = self.elab.push_tga_results(
                    experiment_id=experiment_id,
                    sample_name=sample_name,
                    signals=signals,
                    computed=computed,
                    nomad_url=nomad_url or "",
                    plot_svg=plot_b64,
                )
                if push_ok:
                    result["status"] = "completed"
                    result["nomad_url"] = nomad_url
                    logger.info(f"Pushed results to experiment {experiment_id}")
                else:
                    result["status"] = "push_failed"
                    result["errors"].append(f"Failed to push to experiment {experiment_id}")
                    self.elab.set_error_status(experiment_id, f"Push failed for {sample_name}")
            except Exception as exc:
                result["status"] = "error"
                err = str(exc)
                result["errors"].append(err)
                logger.error(f"Pipeline error for experiment {experiment_id}: {err}")
                self.elab.set_error_status(experiment_id, err)
        elif self.config.dry_run:
            result["status"] = "dry_run"
        else:
            result["status"] = "no_match"
            result["warnings"].append(f"No matching experiment found for '{sample_name}'")

        return result

    def _match_experiment(
        self, sample_name: str, metadata: Dict[str, Any], fmt: str
    ) -> Optional[int]:
        """Try to match the exported file to an elabFTW experiment.

        Matching strategies (in order):
        1. Experiment ID embedded in filename
        2. FIFO: oldest Running experiment without results
        3. Sample name lookup via elabFTW API
        """
        # Strategy 1: Extract experiment ID from filename
        filename = metadata.get("filename", "")
        id_match = re.search(r"_exp(\d+)_", filename)
        if id_match:
            exp_id = int(id_match.group(1))
            logger.info(f"Found experiment ID {exp_id} in filename")
            return exp_id

        # Strategy 2: FIFO - oldest Running experiment without results
        if self.elab:
            queued = self.elab.find_oldest_queued_experiment()
            if queued:
                eid = queued["id"]
                logger.info(f"FIFO matched to experiment {eid} ({queued.get('title','?')})")
                return eid

        # Strategy 3: Search by sample name
        if self.elab:
            exp = self.elab.find_experiment_by_name(sample_name)
            if exp:
                logger.info(f"Matched '{sample_name}' to experiment {exp['id']}")
                return exp["id"]

        return None

    def _compute_results(
        self, fmt: str, signals: Dict[str, List[float]], metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Compute format-specific results from signal data."""
        if fmt == "tga":
            return self._compute_tga(signals, metadata)
        elif fmt == "dma":
            return self._compute_dma(signals, metadata)
        return {}

    def _compute_tga(
        self, signals: Dict[str, List[float]], metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Compute TGA results: Tg, mass loss steps, residue, etc."""
        import numpy as np

        results: Dict[str, Any] = {}

        temp = np.array(signals.get("temperature", []))
        weight = np.array(signals.get("weight", []))
        dta = np.array(signals.get("dta", []))

        if len(weight) == 0:
            return results

        # Normalize weight to percentage
        initial_weight = weight[0] if weight[0] > 0 else 1.0
        weight_pct = (weight / initial_weight) * 100.0

        # Final residue
        results["residue_mass_pct"] = round(float(weight_pct[-1]), 2)
        results["residue_mass_mg"] = round(float(weight[-1]), 4)

        # Temperature at specific mass loss points
        if len(temp) > 0 and len(temp) == len(weight_pct):
            for target_pct, key in [(95, "mass_loss_5pct"), (90, "mass_loss_10pct"), (50, "mass_loss_50pct")]:
                mask = weight_pct <= target_pct
                if np.any(mask):
                    idx = np.argmax(mask)
                    results[key] = round(float(temp[idx]), 1)
                else:
                    results[key] = None

        # Onset temperature (where weight starts to drop significantly)
        if len(temp) > 0 and len(weight_pct) > 10:
            # Find first point where weight_pct drops below 98%
            onset_mask = weight_pct <= 98.0
            if np.any(onset_mask):
                idx = np.argmax(onset_mask)
                results["onset_temperature"] = round(float(temp[idx]), 1)
            else:
                results["onset_temperature"] = None

        # DTG (derivative) calculation
        if len(temp) > 1 and len(weight_pct) > 1:
            dtg = -np.gradient(weight_pct, temp)
            results["dtg_max"] = round(float(np.max(dtg)), 4) if len(dtg) > 0 else None

        # Tg estimation from DTA signal
        if len(dta) > 10 and len(temp) > 10:
            dta_smooth = np.convolve(dta, np.ones(5)/5, mode='valid')
            # Find inflection point (largest step change)
            dta_diff = np.diff(dta_smooth)
            if len(dta_diff) > 0:
                tg_idx = np.argmax(np.abs(dta_diff))
                # Map back to temperature
                offset = (len(dta) - len(dta_smooth)) // 2
                if tg_idx + offset < len(temp):
                    results["tg_glass_transition"] = round(float(temp[tg_idx + offset]), 1)

        # Mass loss step detection
        steps = self._detect_tga_steps(temp, weight_pct)
        if steps:
            results["steps"] = steps

        return results

    def _detect_tga_steps(
        self, temp: "np.ndarray", weight_pct: "np.ndarray"
    ) -> List[Dict[str, Any]]:
        """Detect individual mass loss steps from TG curve."""
        import numpy as np

        steps = []
        if len(weight_pct) < 20:
            return steps

        # Compute DTG for peak detection
        dtg = -np.gradient(weight_pct, temp)
        dtg_smooth = np.convolve(dtg, np.ones(5)/5, mode='same')

        # Find peaks in DTG (mass loss events)
        from scipy.signal import find_peaks
        peaks, properties = find_peaks(
            dtg_smooth,
            height=np.max(dtg_smooth) * 0.05,  # minimum 5% of max peak
            distance=5,  # minimum 5 points between peaks
            prominence=np.max(dtg_smooth) * 0.03,
        )

        for peak_idx in peaks:
            if peak_idx >= len(temp):
                continue

            # Find onset (shoulder before peak)
            onset_idx = max(0, peak_idx - 3)
            for j in range(peak_idx, max(0, peak_idx - 20), -1):
                if dtg_smooth[j] < dtg_smooth[peak_idx] * 0.1:
                    onset_idx = j
                    break

            # Find offset (shoulder after peak)
            offset_idx = min(len(temp) - 1, peak_idx + 3)
            for j in range(peak_idx, min(len(temp) - 1, peak_idx + 20)):
                if dtg_smooth[j] < dtg_smooth[peak_idx] * 0.1:
                    offset_idx = j
                    break

            # Mass loss for this step
            mass_at_onset = weight_pct[onset_idx]
            mass_at_offset = weight_pct[offset_idx]
            step_loss = mass_at_onset - mass_at_offset

            if step_loss < 0.5:  # skip tiny steps
                continue

            step = {
                "onset_temperature": round(float(temp[onset_idx]), 1),
                "offset_temperature": round(float(temp[offset_idx]), 1),
                "peak_dtg_temperature": round(float(temp[peak_idx]), 1),
                "mass_loss_pct": round(float(step_loss), 2),
                "assignment": _assign_tga_step(round(float(temp[peak_idx]), 1)),
            }
            steps.append(step)

        return steps

    def _compute_dma(
        self, signals: Dict[str, List[float]], metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Compute DMA results: Tg from tan delta, storage/loss modulus."""
        import numpy as np

        results: Dict[str, Any] = {}
        temp = np.array(signals.get("temperature", []))
        storage = np.array(signals.get("storage_modulus", []))
        loss = np.array(signals.get("loss_modulus", []))
        tan_delta = np.array(signals.get("tan_delta", []))

        # Tg from tan delta peak
        if len(tan_delta) > 5 and len(temp) == len(tan_delta):
            peak_idx = np.argmax(tan_delta)
            results["tg_tan_delta"] = round(float(temp[peak_idx]), 1)

        # Tg from loss modulus peak
        if len(loss) > 5 and len(temp) == len(loss):
            peak_idx = np.argmax(loss)
            results["tg_loss_modulus"] = round(float(temp[peak_idx]), 1)

        # Storage modulus at glassy and rubbery plateaus
        if len(storage) > 10:
            n = len(storage)
            results["storage_modulus_glass"] = round(float(np.mean(storage[:n//10])), 2)
            results["storage_modulus_rubber"] = round(float(np.mean(storage[-n//10:])), 2)

        return results

    def _generate_plot(
        self, fmt: str, signals: Dict[str, List[float]], computed: Dict[str, Any]
    ) -> Optional[str]:
        """Generate a summary plot as base64 SVG.

        For now returns None — plot generation will be implemented with
        matplotlib or plotly in a later iteration.
        """
        return None

    def _create_nomad_entry(
        self,
        fmt: str,
        sample_name: str,
        parsed: Dict[str, Any],
        computed: Dict[str, Any],
    ) -> Optional[str]:
        """Create a NOMAD entry via the NOMAD API.

        This creates an entry using the instrument_data schema.
        For now returns a placeholder URL — NOMAD API integration
        will be added once the schema is registered on the instance.

        Returns the NOMAD entry URL or None.
        """
        # Placeholder: NOMAD API integration TBD
        # In production, this would POST to /api/v1/entries with the schema data
        return None


def _assign_tga_step(peak_temp: float) -> str:
    """Assign a chemical/physical process to a TGA step based on temperature."""
    if peak_temp < 150:
        return "moisture / solvent evaporation"
    elif peak_temp < 250:
        return "low molecular weight volatiles"
    elif peak_temp < 400:
        return "side-chain / oligomer degradation"
    elif peak_temp < 600:
        return "main polymer backbone degradation"
    elif peak_temp < 800:
        return "carbonization / char formation"
    else:
        return "high-temperature residue decomposition"


# ── Watch folder ─────────────────────────────────────────────────────────────

class WatchFolder:
    """Monitor a directory for new instrument export files."""

    def __init__(self, config: Config, processor: FileProcessor):
        self.config = config
        self.processor = processor
        self._seen_files: set = set()

    def run_once(self, watch_dir: str) -> List[Dict[str, Any]]:
        """Scan the watch directory and process new files."""
        watch_path = Path(watch_dir)
        if not watch_path.exists():
            logger.error(f"Watch directory does not exist: {watch_dir}")
            return []

        # Ensure subdirectories exist
        archive_path = watch_path / self.config.archive_dir
        error_path = watch_path / self.config.error_dir
        processing_path = watch_path / self.config.processing_dir
        for p in [archive_path, error_path, processing_path]:
            p.mkdir(parents=True, exist_ok=True)

        results = []

        # Find new files
        for fpath in sorted(watch_path.iterdir(), key=lambda p: p.stat().st_mtime):
            if not fpath.is_file():
                continue
            if fpath.parent in (archive_path, error_path, processing_path):
                continue
            if fpath.suffix.lower() not in (".csv", ".txt"):
                continue

            # Skip already seen files
            file_key = str(fpath.resolve())
            if file_key in self._seen_files:
                continue
            self._seen_files.add(file_key)

            # Check file is stable (not being written)
            if not self._is_file_stable(fpath):
                logger.debug(f"File not stable yet: {fpath.name}")
                continue

            # Move to processing
            processing_file = processing_path / fpath.name
            if not self.config.dry_run:
                try:
                    shutil.move(str(fpath), str(processing_file))
                except OSError as e:
                    logger.error(f"Could not move {fpath.name}: {e}")
                    continue
            else:
                processing_file = fpath

            # Process
            result = self.processor.process(str(processing_file))

            # Archive or error
            if not self.config.dry_run and processing_file.exists():
                if result["status"] == "completed":
                    shutil.move(str(processing_file), str(archive_path / fpath.name))
                elif result["status"] == "error":
                    shutil.move(str(processing_file), str(error_path / fpath.name))
                elif result["status"] in ("skipped", "no_match"):
                    # Keep in processing for review
                    pass

            results.append(result)

        return results

    def run_forever(self, watch_dir: str):
        """Watch directory continuously."""
        logger.info(f"Watching {watch_dir} (poll every {self.config.watch_poll_seconds}s)")
        while True:
            try:
                results = self.run_once(watch_dir)
                for r in results:
                    logger.info(
                        f"  {r['file']}: {r['status']}"
                        + (f" → exp {r['experiment_id']}" if r.get('experiment_id') else "")
                    )
            except Exception as e:
                logger.error(f"Watch scan error: {e}")
            time.sleep(self.config.watch_poll_seconds)

    @staticmethod
    def _is_file_stable(path: Path, wait_seconds: float = 2.0) -> bool:
        """Check if file is stable (not being written to)."""
        try:
            size1 = path.stat().st_size
            time.sleep(wait_seconds)
            size2 = path.stat().st_size
            return size1 == size2 and size1 > 0
        except OSError:
            return False


# ── CLI ──────────────────────────────────────────────────────────────────────

def setup_logging(verbose: bool = False):
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Instrument data ingest — parse TRIOS exports and push to elabFTW",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be done without making changes",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Verbose logging",
    )
    parser.add_argument(
        "--api-key", type=str,
        help="elabFTW API key (overrides ELABFTW_API_KEY)",
    )
    parser.add_argument(
        "--api-url", type=str,
        help="elabFTW API URL (overrides ELABFTW_API_URL)",
    )
    parser.add_argument(
        "--team", type=int,
        help="elabFTW team ID (overrides ELABFTW_TEAM)",
    )
    parser.add_argument(
        "--watch-poll", type=int, default=60,
        help="Watch mode poll interval in seconds",
    )

    subparsers = parser.add_subparsers(dest="command", help="Command")

    # Process command
    proc_parser = subparsers.add_parser("process", help="Process a file or directory")
    proc_parser.add_argument("target", type=str, help="File or directory to process")

    # Watch command
    watch_parser = subparsers.add_parser("watch", help="Watch a directory continuously")
    watch_parser.add_argument("directory", type=str, help="Directory to watch")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    setup_logging(args.verbose)
    config = Config.from_args(args)

    # Initialize elabFTW client
    elab = None
    if config.elabftw_api_key:
        elab = ElabftwClient(
            api_url=config.elabftw_api_url,
            api_key=config.elabftw_api_key,
            team=config.elabftw_team,
        )
    elif not config.dry_run:
        logger.warning("No ELABFTW_API_KEY set — results will not be pushed back")

    processor = FileProcessor(config, elab)
    watcher = WatchFolder(config, processor)

    if args.command == "process":
        target = args.target
        path = Path(target)
        if path.is_file():
            result = processor.process(target)
            status = result["status"]
            print(f"\nFile: {path.name}")
            print(f"Status: {status}")
            print(f"Format: {result.get('format', 'unknown')}")
            print(f"Sample: {result.get('sample_name', 'unknown')}")
            if result.get("experiment_id"):
                print(f"Experiment: {result['experiment_id']}")
            if result.get("errors"):
                print(f"Errors: {result['errors']}")
            if result.get("warnings"):
                print(f"Warnings: {result['warnings']}")
            if result.get("computed"):
                print(f"Computed: {json.dumps(result['computed'], indent=2, default=str)}")
        elif path.is_dir():
            files = sorted(path.glob("*.csv")) + sorted(path.glob("*.txt"))
            print(f"Processing {len(files)} files in {target}")
            for f in files:
                result = processor.process(str(f))
                print(f"  {f.name}: {result['status']}")
        else:
            print(f"Target not found: {target}")
            sys.exit(1)

    elif args.command == "watch":
        watcher.run_forever(args.directory)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
