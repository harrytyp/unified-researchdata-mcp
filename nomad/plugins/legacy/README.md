# Legacy — archived NOMAD plugin development artifacts (July 2026)

Archived 2026-09-08. Everything in this directory is **superseded or a one-off
script** — nothing here is imported by active runtime code (verified by
import-graph analysis from the runtime roots `instrument_data`,
`nomad_processor`, `nomad_launcher` + startup.sh/compose checks). Kept for
reference and git history. Do not restore to the plugin root.

## Contents

| Group | Files | What it was |
|---|---|---|
| E2E experiment scripts | `e2e_*.py`, `full_e2e.py`, `final_e2e_*.py`, `final_full_e2e.py`, `mock_trios_run.py`, `process_*.py`, `check_*.py`, `test_tri_format_manual.py` | One-off end-to-end tests of the July elabFTW/NOMAD pipeline |
| DB/state fix scripts | `fix_*.py`, `patch_*.py`, `clean_*.py`, `clear_processed.py`, `create_elab_item.py`, `find_*.py`, `debug_nomad_cfg.py` | One-off Mongo/parser/schema repairs during development |
| Superseded stacks | `elab_watcher_service.py`, `e2e_tga_service.py`, `tga_watch.py` | Older copies of the elabFTW watcher (v1 lineage; also archived under `tga/legacy/elabftw-watcher-v1/`) |
| Old plugin generations | `instrument_data_old/`, `elabftw_linker/`, `three_way_sync/`, `instrument_data_loader.py`, `instrument_ingest.py`, `add_xlsx_parser.py` | Predecessor plugin structures before the current `instrument_data/` package |
| Test data | `test_watch/`, `instrument-exports/`, `sample_files-testdata/`, `tprc-testoutputs/` | Screenshots, .tri/.xlsx/.SPA/.bin samples, generated test `.tprc`s |
| Tooling | `setup.bat`, `patch_all*.py` etc. | Windows venv bootstrap (refs `tga_watch.py`) and bulk patchers |

## Key reference note

`sample_files-testdata/TGA_Char yield 1Cmin 1000C.tprc` is the OLD v2 template
that `tprc_builder.py` v2 patched. The current v3 builder does NOT use it —
it builds from `sample_files/empty.tprc` (kept active) + inserted SGMT blocks.
