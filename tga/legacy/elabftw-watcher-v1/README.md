# Legacy: elabFTW Watcher v1 (July 2026) — DEPRECATED, kept for reference

This directory is the **first-generation** TGA pipeline (v1), archived 2026-09-08.
It is **not used** by the current system — do not run, port, or copy from it.

## What it was

A client-side watcher stack that:
1. Polled elabFTW experiments (`elab_watcher_service.py`)
2. Generated `.tprc` procedure files **locally** by patching a foreign TRIOS
   template file (`tprc_builder.py` v2 — template-patching approach)
3. Parsed `.tri` measurement exports (`e2e_tga_service.py`)
4. Uploaded results back to NOMAD / attached to elabFTW

## Why it is archived

- `.tprc` generation is now **server-side**: `nomad/plugins/tprc_builder.py` v3
  builds from `empty.tprc` (TRIOS 6.1 export) + inserts exactly one SGMT block per
  entered segment — no foreign template segments remain (see its docstring).
- elabFTW was deprioritized; the operator app (`tga/tga_v2/`) talks to NOMAD directly.
- The v2 EXE (`tga/dist/TGA_Operator.exe`) contains **no** tprc_builder code —
  it only uploads server-generated `.tprc` files.

## Files

| File | Role (historical) |
|---|---|
| `elab_watcher_service.py` | elabFTW experiment watcher (v2 status tracking) |
| `e2e_tga_service.py` | `.tri` parsing + NOMAD upload service |
| `tprc_builder.py` | **v2** template-patching builder — superseded by server v3 |
| `tga_elab_app.pyw` | Windows elabFTW GUI app (pre-NiceGUI) |
| `requirements.txt` | v1 dependencies |
