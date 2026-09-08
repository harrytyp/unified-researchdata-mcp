# TGA Operator App — Directory Overview

## Active (current architecture)

- **`tga_v2/`** — TGA Operator App v2 (NiceGUI). The operator UI: board/list/detail,
  NOMAD upload of TRIOS result files (`.tri` / `.json`) into the existing upload,
  i18n, dark mode. This is the source of the EXE.
- **`dist/`** — `TGA_Operator.exe`, built from `tga_v2/` (PyInstaller onefile,
  native pywebview window). Ships to the lab PC; the desktop copy on the lab
  machine is the same build.

## Legacy (kept for reference, NOT in use)

- **`legacy/elabftw-watcher-v1/`** — July 2026 elabFTW-watcher stack (v1): polled
  elabFTW experiments, generated `.tprc` client-side by patching a foreign TRIOS
  template (`tprc_builder.py` v2), attached results back to elabFTW. Superseded:
  - `.tprc` generation moved server-side to the NOMAD plugin
    (`nomad/plugins/tprc_builder.py` v3: builds from `empty.tprc` + SGMT blocks).
  - elabFTW was deprioritized; the operator app (`tga_v2`) talks to NOMAD directly.
  - The v2 EXE contains NO tprc_builder code (verified: 0 SGMT/LengthTagged hits) —
    it only uploads `.tprc` files that the NOMAD server generated.
  Kept as historical reference. Do not port, do not use as template base.

## Architecture note

`.tprc` files are generated **server-side only** (NOMAD plugin `instrument_data`),
never by the EXE. The EXE uploads measurement results into the upload that holds
the `.tprc` and the TgaMeasurement entry.
