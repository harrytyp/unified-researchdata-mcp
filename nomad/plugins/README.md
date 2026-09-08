# NOMAD Plugins — Directory Overview

This directory is volume-mounted into the NOMAD containers as `/app/plugins`
(see `docker-compose.yaml`). Only the ACTIVE files below are used at runtime;
everything historical lives in `legacy/`.

## Active (runtime, do not move/rename)

| Path | Purpose |
|---|---|
| `instrument_data/` | TGA/DMA/FTIR/MS schema + processor + parsers (NOMAD plugin, registered via `startup.sh` entry_points) |
| `nomad_processor.py` | Poller/watch loop started by `startup.sh` (`python3 nomad_processor.py watch`) |
| `nomad_launcher.py` | Entry wrapper for compose services `logtransfer` + `hub` |
| `tprc_builder.py` | **v3** `.tprc` builder: `empty.tprc` base + one SGMT block per entered segment |
| `sample_files/empty.tprc` | TRIOS 6.1 empty-procedure base for `tprc_builder.py` (only file still referenced) |
| `startup.sh` | App container entrypoint (entry_points, processor watch, uploads-admin patch) |
| `patch_uploads_admin.sh` | Patches NOMAD `uploads.py` so admins see all uploads (run by startup.sh) |

## Not tracked / runtime state

- `.volumes/` — NOMAD filesystem (staging, tmp); NOT application code.
  **Note:** some old E2E test artifacts under `.volumes/fs/` were accidentally
  committed to git in the past — candidates for `git rm --cached` cleanup.
- `run/` — runtime marker dir (`gui_configured`).
- `__pycache__/` — Python bytecode.

## Legacy

`legacy/` — archived one-off scripts and superseded stacks from the July 2026
development phase (E2E experiments, DB-fix scripts, old parsers,
elabFTW-watcher copies, sample test files, generated test `.tprc`s). Kept for
reference, NOT imported by any active code (verified by import-graph analysis,
2026-09-08). See `legacy/README.md`.
