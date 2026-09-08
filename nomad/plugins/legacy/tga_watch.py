#!/usr/bin/env python3
"""
TGA Uploader for Windows — watch folder, upload raw exports to NOMAD.

The heavy lifting (parsing, computation, elabFTW push) happens server-side
via NOMAD's normalizer/instrument_ingest pipeline.

Commands:
  setup     First-time configuration (API keys, paths)
  upload    One-shot: upload a CSV to NOMAD + link to elabFTW item
  watch     Continuous: monitor a directory for new exports

Dependencies: requests
Install:  pip install requests
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("tga-uploader")

# ── Config ───────────────────────────────────────────────────────────────────

CONFIG_DIR = Path(os.environ.get("APPDATA", Path.home() / ".config")) / "tga-automation"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_CONFIG = {
    "watch_dir": "Z:\\data\\tga-exports",
    "elabftw_url": "https://elntest.ub.tum.de/api/v2",
    "elabftw_team": 29,
    "nomad_url": "https://researchmcp.duckdns.org/nomad-oasis/api/v1",
    "poll_interval": 60,
    "archive_dir": "processed",
    "error_dir": "errors",
    "companion_extensions": [".csv", ".txt", ".dat", ".tpc", ".ispc", ".exp"],
}


def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not load config: {e}")
    return dict(DEFAULT_CONFIG)


def save_config(cfg: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)
    logger.info(f"Config saved to {CONFIG_FILE}")


# ── elabFTW Client (via curl.exe — no SSL issues) ────────────────────────────


class ElabftwClient:
    """Lightweight elabFTW API client. Only needs: matching, status, no results push."""

    def __init__(self, api_url: str, api_key: str, team: int = 29, timeout: int = 30):
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.team = team
        self.timeout = timeout

    def _curl(self, method: str, url: str, data: Optional[str] = None,
              files: Optional[dict] = None, params: Optional[dict] = None,
              timeout: Optional[int] = None) -> Optional[dict]:
        import subprocess as _sp
        import json as _json
        cmd = ["curl", "-s", "--max-time", str(timeout or self.timeout),
               "-X", method, "-H", "Authorization: " + self.api_key]
        if params:
            for k, v in params.items():
                cmd += ["--data-urlencode", f"{k}={v}"]
        if data:
            cmd += ["-H", "Content-Type: application/json", "-d", data]
        if files:
            for field, filepath in files.items():
                cmd += ["-F", f"{field}=@{filepath}"]
        cmd.append(url)
        try:
            proc = _sp.run(cmd, capture_output=True, text=True, timeout=timeout or self.timeout)
            if proc.returncode != 0:
                logger.warning(f"curl error ({proc.returncode}): {proc.stderr[:200]}")
                return None
            if not proc.stdout.strip():
                return {}
            return _json.loads(proc.stdout)
        except Exception as e:
            logger.error(f"curl failed: {e}")
            return None

    def _req(self, method: str, path: str, **kwargs) -> Optional[dict]:
        url = f"{self.api_url}/{path.lstrip('/')}"
        data = kwargs.get("data") or kwargs.get("json")
        if isinstance(data, dict):
            data = json.dumps(data)
        return self._curl(method, url, data=data, params=kwargs.get("params"))

    def get_item(self, item_id: int) -> Optional[dict]:
        return self._req("GET", f"items/{item_id}")

    def find_items_by_status(self, status_id: int, item_type_id: int = 145) -> List[dict]:
        result = self._req("GET", "items", params={
            "status_ids[]": status_id, "cat": item_type_id,
            "order": "created_at", "sort": "asc", "limit": 50,
        })
        return result if isinstance(result, list) else []

    def set_item_status(self, item_id: int, status_name: str) -> bool:
        return self._curl("PATCH", f"{self.api_url}/items/{item_id}",
                          data=f'{{"status": "{status_name}"}}') is not None

    def match_fifo_item(self, filepath: Optional[Path] = None, item_type_id: int = 145
                        ) -> Optional[int]:
        """Match file to elabFTW item: 1) filename ID, 2) FIFO Ready."""
        # Strategy 1: embedded item ID in filename (_item123_)
        if filepath:
            m = re.search(r"_item(\d+)(?:[._]|$)", filepath.stem)
            if m:
                item_id = int(m.group(1))
                if self.get_item(item_id):
                    logger.info(f"Filename match: item {item_id}")
                    return item_id

        # Strategy 2: FIFO — oldest queued item
        items = self.find_items_by_status(status_id=67, item_type_id=item_type_id)
        if items:
            item_id = items[0].get("id")
            if item_id:
                logger.info(f"FIFO match: item {item_id}")
                return item_id

        logger.info("No matching item found")
        return None


# ── NOMAD Push ───────────────────────────────────────────────────────────────


def push_to_nomad(
    nomad_url: str,
    pat: str,
    file_paths: List[Path],
    elabftw_item_id: Optional[int] = None,
    elabftw_url: Optional[str] = None,
    sample_name: str = "",
) -> Optional[str]:
    """Upload files to NOMAD as one upload. Returns NOMAD upload URL or None."""
    import requests as req
    import json as _json

    headers = {"Authorization": f"Bearer {pat}"}
    base_url = nomad_url.rstrip("/")

    # Build metadata
    meta = {"measurement_type": "TGA", "upload_tool": "tga-uploader-windows"}
    if elabftw_item_id:
        meta["elabftw_item_id"] = elabftw_item_id
    if elabftw_url:
        meta["elabftw_url"] = elabftw_url
    if sample_name:
        meta["sample_name"] = sample_name
    data_fields = {"metadata": _json.dumps(meta)}

    # Attach all files
    files = {}
    for fp in file_paths:
        if fp.exists():
            files["file"] = (fp.name, open(fp, "rb"))
            # NOMAD multipart upload uses 'file' field; only one primary file
            # Additional files go as 'file2', 'file3', etc.
            break  # for now single file — can extend to multi-file

    if not files:
        logger.warning("No files to upload")
        return None

    try:
        r = req.post(f"{base_url}/uploads", headers=headers,
                     files=files, data=data_fields, timeout=30)
    except Exception as e:
        logger.error(f"NOMAD upload error: {e}")
        return None
    finally:
        for f in files.values():
            if hasattr(f, "close"):
                f.close()

    if r.status_code in (200, 201):
        upload_id = ""
        # Try JSON response
        try:
            if r.text.strip().startswith("{"):
                upload_id = r.json().get("upload_id", "")
        except (ValueError, json.JSONDecodeError):
            pass
        # Fallback: query uploads list
        if not upload_id:
            try:
                time.sleep(1)
                list_r = req.get(
                    f"{base_url}/uploads?limit=5&order_by=upload_create_time&order=desc",
                    headers=headers, timeout=10)
                if list_r.status_code == 200:
                    for upl in list_r.json().get("data", []):
                        if upl.get("upload_name") == files["file"][0]:
                            upload_id = upl.get("upload_id", "")
                            break
            except Exception:
                pass

        if upload_id:
            url = f"{base_url.replace('/api/v1', '')}/gui/user/uploads/{upload_id}"
            logger.info(f"NOMAD upload: {upload_id}")
            return url

    logger.warning(f"NOMAD upload failed: {r.status_code}")
    return None


# ── Commands ─────────────────────────────────────────────────────────────────


def cmd_setup(args):
    """Interactive setup."""
    cfg = load_config()
    cfg["watch_dir"] = input(f"Watch directory [{cfg.get('watch_dir')}]: ") or cfg["watch_dir"]
    print("\n--- elabFTW ---")
    cfg["elabftw_url"] = input(f"API URL [{cfg.get('elabftw_url')}]: ") or cfg["elabftw_url"]
    k = input(f"API Key [{cfg.get('elabftw_api_key','')[:12]}...]: ") or ""
    if k:
        cfg["elabftw_api_key"] = k
    cfg["elabftw_team"] = int(input(f"Team ID [{cfg.get('elabftw_team',29)}]: ") or cfg.get("elabftw_team",29))
    print("\n--- NOMAD ---")
    cfg["nomad_url"] = input(f"API URL [{cfg.get('nomad_url')}]: ") or cfg["nomad_url"]
    p = input(f"PAT [{cfg.get('nomad_pat','')[:20]}...]: ") or ""
    if p:
        cfg["nomad_pat"] = p
    save_config(cfg)
    print("\n✓ Saved. Next: python tga-uploader.py watch")


def cmd_upload(args):
    """Upload a single CSV to NOMAD + link to elabFTW item."""
    config = load_config()
    path = Path(args.file)
    if not path.exists():
        logger.error(f"File not found: {path}")
        return 1

    # Detect format (basic validation)
    fmt = detect_format(str(path))
    if not fmt:
        logger.warning(f"Unknown instrument format: {path}")
        return 1

    sample_name = path.stem
    logger.info(f"Uploading {path.name} ({fmt})")

    # elabFTW: match item, set to Running
    elab = None
    elab_item_id = None
    elab_url = ""
    if config.get("elabftw_api_key"):
        elab = ElabftwClient(
            api_url=config["elabftw_url"],
            api_key=config["elabftw_api_key"],
            team=config["elabftw_team"],
        )
        elab_item_id = elab.match_fifo_item(filepath=path)
        if elab_item_id:
            elab.set_item_status(elab_item_id, "Running")
            elab_url = f"{config['elabftw_url'].rstrip('/api/v2')}/database.php?mode=view&id={elab_item_id}"
            logger.info(f"Linked to elabFTW item {elab_item_id}")

    # Collect companion files
    files_to_upload = [path]
    for ext in config.get("companion_extensions", []):
        comp = path.with_suffix(ext)
        if comp != path and comp.exists():
            files_to_upload.append(comp)

    # Upload to NOMAD
    if config.get("nomad_pat"):
        nomad_url = push_to_nomad(
            nomad_url=config["nomad_url"],
            pat=config["nomad_pat"],
            file_paths=files_to_upload,
            elabftw_item_id=elab_item_id,
            elabftw_url=elab_url,
            sample_name=sample_name,
        )
        if nomad_url:
            logger.info(f"NOMAD: {nomad_url}")
        else:
            logger.warning("NOMAD upload failed")

    logger.info(f"✓ {path.name} → NOMAD" + (f" + elabFTW item {elab_item_id}" if elab_item_id else ""))
    return 0


def cmd_watch(args):
    """Continuously monitor a directory."""
    config = load_config()
    watch_dir = args.dir or config.get("watch_dir", "")
    if not watch_dir:
        logger.error("No watch directory. Run 'setup' first.")
        return 1

    poll = args.poll or config.get("poll_interval", 60)
    archive = Path(watch_dir) / config.get("archive_dir", "processed")
    error_dir = Path(watch_dir) / config.get("error_dir", "errors")
    archive.mkdir(parents=True, exist_ok=True)
    error_dir.mkdir(parents=True, exist_ok=True)
    seen: set = set()

    logger.info(f"Watching {watch_dir} (poll {poll}s)")
    try:
        while True:
            for fpath in sorted(Path(watch_dir).iterdir(), key=lambda p: p.stat().st_mtime):
                if not fpath.is_file() or fpath.parent in (archive, error_dir):
                    continue
                if fpath.suffix.lower() not in (".csv", ".txt", ".dat"):
                    continue
                if str(fpath.resolve()) in seen:
                    continue
                if not _is_stable(fpath):
                    continue

                seen.add(str(fpath.resolve()))
                fmt = detect_format(str(fpath))
                if not fmt:
                    continue

                result = cmd_upload(
                    argparse.Namespace(file=str(fpath), dry_run=False)
                )
                if result == 0:
                    shutil.move(str(fpath), str(archive / fpath.name))
                else:
                    shutil.move(str(fpath), str(error_dir / fpath.name))
            time.sleep(poll)
    except KeyboardInterrupt:
        logger.info("Stopped.")


def _is_stable(path: Path, checks: int = 3) -> bool:
    try:
        sizes = [path.stat().st_size for _ in range(checks)]
        time.sleep(0.3)
        return len(set(sizes)) == 1
    except OSError:
        return False


# ── Format detection (minimal — just enough to validate) ──────────────────────


def detect_format(filepath: str) -> Optional[str]:
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            head = f.read(4096)
    except Exception:
        return None
    hl = head.lower()
    if any(kw in hl for kw in ["tga", "thermogravimetric"]):
        return "tga"
    if any(kw in hl for kw in ["dma", "dynamic mechanical"]):
        return "dma"
    if any(kw in hl for kw in ["ftir", "fourier transform", "infrared"]):
        return "ftir"
    if any(kw in hl for kw in ["mass spectrometer", "mass spec"]):
        return "ms"
    for line in head.splitlines():
        if line.startswith("Instrument type") or line.startswith("Instrument name"):
            if "tga" in line.lower():
                return "tga"
            if "dma" in line.lower():
                return "dma"
    return None


# ── Entry Point ──────────────────────────────────────────────────────────────


def main():
    p = argparse.ArgumentParser(description="TGA Uploader — watch + upload to NOMAD")
    sub = p.add_subparsers(dest="command")
    sub.add_parser("setup", help="Configure API keys and paths")
    up = sub.add_parser("upload", help="Upload a file to NOMAD + link to elabFTW")
    up.add_argument("file", help="Path to CSV/TXT file")
    wa = sub.add_parser("watch", help="Monitor directory for new exports")
    wa.add_argument("dir", nargs="?", help="Directory to watch")
    wa.add_argument("--poll", type=int, help="Poll interval in seconds")
    sub.add_parser("show-config", help="Display current configuration")

    args = p.parse_args()
    if args.command == "setup":
        cmd_setup(args)
    elif args.command == "upload":
        return cmd_upload(args)
    elif args.command == "watch":
        return cmd_watch(args)
    elif args.command == "show-config":
        cfg = load_config()
        for k, v in cfg.items():
            if "key" in k.lower() or "pat" in k.lower():
                v = f"{str(v)[:12]}..." if v else "(not set)"
            print(f"  {k}: {v}")
    else:
        p.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
