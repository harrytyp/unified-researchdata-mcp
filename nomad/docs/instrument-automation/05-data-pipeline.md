# Data Pipeline: NOMAD Ingestion & elabFTW Push-Back

> **Status**: Planned / To be built. This document describes the architecture
> for the automated data pipeline that ingests instrument exports into NOMAD and
> pushes results back to elabFTW.

## Architecture

```
TRIOS auto-export
      │  CSV/TXT files
      ▼
Watch Folder (server filesystem)
      │  inotify / cron poll
      ▼
NOMAD Ingest Script
      │  python3 + numpy + scipy
      ├── Parser: extract metadata + signal data
      ├── Compute: TG, DTG, peak detection, curve fitting
      ├── Plot: generate summary graph
      └── Create: NOMAD entry via NOMAD API
      │
      ├────────────────────────────────────┐
      │                                    │
      ▼                                    ▼
NOMAD Entry                          elabFTW Experiment
(TgaMeasurement structured schema)   (PATCH body + metadata + status="Success")
```

## Components Built

### 1. NOMAD Schema Package: `instrument_data`

Location: `plugins/instrument_data/`

**Status: Built** ✅

| File | Purpose |
|------|---------|
| `schema.py` | NOMAD EntryData schemas: `TgaMeasurement`, `DmaMeasurement`, `FtrMeasurement`, `MsMeasurement` — each with sample info, method params, signal curves, computed results, and elabFTW ref |
| `entrypoint.py` | NOMAD plugin registration (`instrument-schema` entry point) |
| `parser.py` | CSV/TXT parser for TRIOS-exported files — handles tab-separated `[Section]` format, extracts metadata + multi-column signal data |
| `elabftw_client.py` | elabFTW API client for automation — find experiments, PATCH body/metadata/status, upload files, push TGA results with formatted HTML |
| `pyproject.toml` | Package metadata with `nomad.plugin` entry point |
| `instrument_data.egg-info/` | Installed into NOMAD via `startup.sh` |

### 2. Ingest Script: `instrument-ingest`

Location: `scripts/instrument_ingest.py`

**Status: Built** ✅

- **One-shot mode**: `python instrument_ingest.py process <file_or_dir>`
- **Watch mode**: `python instrument_ingest.py watch <directory>`
- File detection → format detection → parsing → experiment matching → results computation → elabFTW push-back
- TGA results: Tg (DTA inflection), residue, onset, mass loss steps (DTG peak detection), Td5/Td10/Td50
- DMA results: Tg from tan delta peak, Tg from loss modulus peak, storage modulus glassy/rubbery plateaus
- Dry-run mode: `--dry-run` to preview without writing

```python
class TgaMeasurement(EntryData):
    """TGA measurement with parsed results."""
    sample_name = Quantity(type=str)
    sample_mass = Quantity(type=float, unit="mg")
    crucible_type = Quantity(type=str)
    procedure = Quantity(type=str)
    gas_atmosphere = Quantity(type=str)
    flow_rate = Quantity(type=float, unit="mL/min")
    raw_data = Quantity(type=str)  # file reference
    tg_curve = Quantity(type=JSON)  # [[temp, weight%], ...]
    dtg_curve = Quantity(type=JSON)
    results = SubSection(sub_section=TgaResults)
    elabftw_ref = SubSection(sub_section=ElabftwExperimentRef)
```

Similarly for `DmaMeasurement`, `FtrMeasurement`, `MsMeasurement`.

### 2. CSV/TXT Parser

A Python module that reads TRIOS-exported CSV/TXT files:

```
Parser interface:
  detect_format(filepath) -> "tga" | "dma" | "ftir" | "ms" | None
  parse_metadata(filepath) -> dict  (sample name, mass, operator, ...)
  parse_signals(filepath) -> dict   (time, temperature, weight, ...)
  compute_results(signals) -> dict  (tg, onset, residue, ...)
```

**TGA parser specifics:**
- Read tabular data between header and trailing metadata
- Column detection: find "Temperature", "Weight", "Time" headers
- Weight normalization: absolute (mg) → relative (%)
- DTG computation: central difference derivative
- Peak detection: scipy.signal.find_peaks on DTG
- Tg detection: step change in DTA signal or midpoint method
- Mass step detection: plateau identification between DTG peaks

### 3. Watch Folder Script

A Python script (runs as systemd service or Docker container) that:

1. Polls a configured directory for new `.csv`/`.txt` files
2. Moves files to a processing queue (atomic rename)
3. Calls the parser for each file
4. Matches the file to an elabFTW experiment (via sample name / file naming convention)
5. Creates a NOMAD entry via the NOMAD API
6. Pushes results back to elabFTW via the elabFTW API
7. Moves processed files to an archive directory

**Configuration:**

```yaml
watch_dir: /data/instrument-exports/
archive_dir: /data/instrument-exports/processed/
error_dir: /data/instrument-exports/errors/
elabftw:
  api_url: https://elntest.ub.tum.de/api/v2
  api_key: ${ELABFTW_API_KEY}
  team: 29
nomad:
  api_url: http://nomad_oasis_app:8000/api/v1
poll_interval_seconds: 60
```

### 4. elabFTW Link-Back

After NOMAD entry creation, push results back:

```python
def push_results_to_elabftw(experiment_id, results, plot_svg, nomad_url):
    """Update elabFTW experiment with parsed results."""

    # Build HTML body with results table + chart
    body = f"""
    <h2>Results: {results['sample_name']}</h2>
    <table>
      <tr><td>Tg</td><td>{results['tg_celsius']} °C</td></tr>
      <tr><td>Residue</td><td>{results['residue_pct']} %</td></tr>
      <tr><td>NOMAD Link</td><td><a href="{nomad_url}">{nomad_url}</a></td></tr>
    </table>
    <img src="data:image/svg+xml;base64,{base64_plot}" />
    """

    # PATCH experiment
    requests.patch(
        f"{api_url}/experiments/{experiment_id}",
        headers={"Authorization": api_key},
        json={
            "body": body,
            "metadata": json.dumps({
                "nomad_url": nomad_url,
                "nomad_results": results,
                "nomad_synced": datetime.now(timezone.utc).isoformat()
            }),
            "status": 123  # "Success"
        }
    )
```

### 5. Deployment

All components run inside the existing NOMAD Oasis Docker network or as a
standalone container with access to both the watch folder and the NOMAD API.

**Option A: NOMAD startup.sh plugin**
- Add `instrument_data` schema package to the existing startup.sh
- The normalizer runs inside NOMAD's worker processes

**Option B: Standalone Docker container**
- New container in the docker-compose.yml
- Mounts the watch folder as a volume
- Has access to the NOMAD API via the Docker network
- Runs the watch/poll loop continuously

**Option C: Hermes cron job**
- Uses Hermes Agent's cronjob scheduler
- Polls the folder and processes files
- Simpler to set up but less robust

## TRIOS Auto-Export Configuration

In TRIOS software, enable automatic export:
1. Go to **Tools → Options → Export**
2. Check **"Automatically export data after run"**
3. Select format: **CSV** or **TXT** (ASCII)
4. Set output directory to the **watch folder**
5. Naming convention: `{Instrument}_{SampleName}_{Date}_{Time}.csv`

The supplier confirmed this feature exists:
> "Automatical export into ascii/JSON is possible by selecting the checkmark
> in the SW options."

## File Naming Convention

Recommended format for auto-matching with elabFTW experiments:

```
{InstrumentAbbrev}_{SampleName}_{ExperimentID}_{Timestamp}.csv
```

Example: `TGA_Polymer-X_4688_20251031_144752.csv`

The `ExperimentID` in the filename allows direct matching to the elabFTW
experiment. If not available, matching falls back to:
- Sample name lookup (via elabFTW API search)
- Creation date proximity
- Manual assignment

## Data Flow Diagram

```
┌──────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────┐
│ TRIOS    │───►│ Watch Folder │───►│ Parser       │───►│ NOMAD    │
│ auto-    │    │              │    │ (Python)     │    │ Entry    │
│ export   │    │ /data/tga/   │    │              │    │          │
└──────────┘    └──────────────┘    └──────┬───────┘    └──────────┘
                                           │
                                           ▼
                                    ┌──────────────┐
                                    │ elabFTW API   │
                                    │ PATCH exp     │
                                    │ body+metadata │
                                    │ status=Success│
                                    └──────────────┘
```

## Test Files

Sample instrument data is available locally at:
- `~/Downloads/tgaautomation/sample files/`

These are **not** committed to the repository (binary proprietary formats,
see `.gitignore`). Use them as test input when developing the parser.
