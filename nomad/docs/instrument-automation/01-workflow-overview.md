# A-to-Z Workflow: From User Request to Parsed Results

This document describes the complete end-to-end flow for instrument measurements,
from the moment a scientist books an instrument to the final parsed results appearing
in their elabFTW experiment.

---

## Phase 1: Request & Booking (User)

### 1a. Browse Available Instruments

The user navigates to **elabFTW → eConversion DataIntelligence → Database → Devices&Tools**
and sees four bookable instrument items:

| Instrument | Item ID | Category |
|------------|---------|----------|
| TGA (TA Waters / TRIOS) | 1367 | Devices&Tools |
| DMA (TA Waters / TRIOS) | 1368 | Devices&Tools |
| FTIR Spectrometer | 1369 | Devices&Tools |
| Mass Spectrometer | 1370 | Devices&Tools |

Each item displays:
- Instrument specifications and capabilities
- A **Booking** tab with an interactive calendar
- Up to 60 days advance booking, max 8 hours per slot

### 1b. Book a Time Slot

1. Click on the desired instrument (e.g. **TGA (TA Waters / TRIOS)**)
2. Go to the **Booking** tab
3. Select an available time slot on the calendar
4. Confirm the booking

The booking is stored as an event linked to the instrument resource. No overlaps
are allowed (`book_can_overlap=0`).

### 1c. Create Experiment from Template

1. In elabFTW, click **Create experiment from template**
2. Select the instrument-specific template (e.g. **TGA Measurement**)
3. A new experiment is created with all parameter fields pre-defined as structured
   **extra_fields** (not just free-text):

| Field | Type | Example |
|-------|------|---------|
| Sample Name | text | "Polymer-X" |
| Sample Mass [mg] | number | 12.5 |
| Crucible Type | select | Alumina / Platinum / Aluminum |
| Temperature Start [°C] | number | 30 |
| Temperature End [°C] | number | 600 |
| Heating Rate [K/min] | number | 10 |
| Gas Atmosphere | select | N2 / Air / Ar / Synthetic Air / O2 |
| Gas Flow Rate [mL/min] | number | 50 |
| Operator | text | (assigned by lab) |
| Autosampler Position | number | 5 |
| Method File (.TRPC) | text | (reference) |
| Notes | textarea | "Check for decomposition" |

4. Link the experiment to the booked instrument item (via elabFTW's linking)
5. Set status to **"Running"** — this signals the operator that a job is ready

### 1d. Bring Physical Sample

The user places their physical sample in the designated lab location, labeled
with the experiment ID or sample name for traceability.

---

## Phase 2: Operator Review & Measurement (Technician)

### 2a. Review Queue

The operator checks **elabFTW → Experiments** filtered by:
- Status = **Running**
- Category / tags matching instrument templates

Each experiment shows all parameters pre-filled from the extra_fields. No
paper forms, no emails — everything is in elabFTW.

### 2b. Load Sample

1. Locate the physical sample (brought by the user in Phase 1d)
2. Load it into the instrument's **autosampler** at the position specified in
   the experiment parameters
3. Tare the pan if using the autosampler (standard TRIOS workflow)

### 2c. Accept the Request

The operator marks the job as accepted — either by:
- Changing experiment status to a custom "Accepted" / "In progress" status, or
- A checkbox in elabFTW extra_fields

This step confirms the sample is loaded and the instrument is ready.

### 2d. Run the Measurement

The TRIOS software reads the method parameters from the experiment and runs
the measurement automatically. The autosampler processes queued samples in sequence.

---

## Phase 3: Data Export (TRIOS)

### 3a. Auto-Export Configuration

TRIOS is configured (via **SW Options → checkmark**) to **automatically export**
measurement data as CSV or TXT after each run completes.

### 3b. Export Format

The exported file contains:

```
Filename    AC1BAPO UV CURED 5KMIN 1000C N2
Instrument  0550-1823 (192.168.0.3)
Operator    PB
Sample Name AC1BAPO UV CURED 5KMIN 1000C N2
Sample Mass 53.504 mg
Pan Type    Platinum HT
Procedure   Char yield with gas and without air cool and with gas 1 (Nitrogen)

[Signals]
Time (min) | Temperature (°C) | Weight (mg) | DTA (°C) | Purge (mL/min)
  0.0      |   30.0           |  53.504     |  0.00    |  40.0
  0.5      |   32.5           |  53.502     |  0.01    |  40.0
  ...      |   ...            |  ...        |  ...     |  ...
```

### 3c. File Destination

The CSV/TXT is written to a **shared/network folder** that is accessible to the
NOMAD Oasis server (mounted network share or watch folder).

---

## Phase 4: Data Ingestion & Parsing (NOMAD Oasis)

### 4a. Watch Folder Detection

A NOMAD background job (or systemd cron) polls the watch folder for new
CSV/TXT files. When a new file appears:

1. File is moved to a processing queue (atomic rename to avoid partial reads)
2. File naming convention: `{Instrument}_{SampleName}_{Date}_{Time}.csv`
3. A processing lock prevents duplicate ingestion

### 4b. Parser: Extract Metadata

The parser reads the header section of the CSV/TXT and extracts:

| Metadata field | Source in file |
|----------------|---------------|
| Instrument name | "Instrument name" line |
| Sample name | "Sample Name" line |
| Sample mass | "Sample Mass" line (parses "53.504 mg") |
| Pan type | "Pan Type" line |
| Operator | "Operator" line |
| Run date | "Run date" line |
| Procedure | "Procedure Name" line |
| Procedure segments | "proceduresegments" line (heating profile) |
| Gas atmosphere | Parsed from procedure or Gas Type line |

### 4c. Parser: Extract Signal Data

The parser reads the tabular data section and extracts numeric columns:

| Signal | Unit | Column |
|--------|------|--------|
| Time | min | Column 1 |
| Temperature | °C | Column 2 |
| Weight | mg | Column 3 |
| DTA (Temperature Difference) | °C | Column 4 |
| Purge Flow | mL/min | Column 5 |

### 4d. Compute Derived Quantities (TGA-specific)

From the raw weight signal, the parser computes:

- **TG curve**: Weight % vs Temperature (normalized)
- **DTG curve**: First derivative of weight vs time/temperature
- **Mass loss steps**: Detected via DTG peak finding
- **Onset/Offset temperatures**: For each mass loss step
- **Tg (glass transition)**: Step change in DTA signal
- **Residue mass**: Final stable weight at end of run

### 4e. Create NOMAD Entry

A structured `TgaMeasurement` entry is created in NOMAD Oasis:

```yaml
TgaMeasurement:
  sample_name: "Polymer-X"
  sample_mass: 12.5 mg
  crucible_type: Alumina
  procedure: "Ramp 5°C/min to 1000°C"
  gas: N2
  flow_rate: 40 mL/min
  raw_data: { file: "TGA_Polymer-X_2025-10-31.csv" }
  tg_curve: [ [30, 100], [100, 98.2], ... ]  # Temperature vs Weight%
  dtg_curve: [ [30, 0], [350, -0.5], ... ]   # Temperature vs dWeight/dt
  results:
    tg: 125.3 °C
    mass_loss_5pct: 320 °C
    mass_loss_95pct: 580 °C
    residue: 2.1 %
    steps:
      - temperature_range: "30-150°C"
        mass_loss: 3.2 %
        type: "moisture / solvent evaporation"
      - temperature_range: "350-500°C"
        mass_loss: 68.4 %
        type: "main polymer degradation"
      - temperature_range: "500-800°C"
        mass_loss: 26.3 %
        type: "carbonization"
  elabftw_ref:
    experiment_id: 4688
    elabftw_url: "https://elntest.ub.tum.de/experiments.php?mode=view&id=4688"
```

### 4f. Generate Summary Plot

A summary plot is generated showing:
- TG curve (Weight % vs Temperature) — left Y axis
- DTG curve (dWeight/dt vs Temperature) — right Y axis
- Annotated mass loss steps
- Key temperatures (Tg, onset, etc.)

Output: SVG or PNG image + interactive Plotly HTML.

---

## Phase 5: Results Push-Back to elabFTW

### 5a. Update Experiment Body

The NOMAD pipeline PATCHes the elabFTW experiment via the API:

```json
PATCH /api/v2/experiments/{id}
{
  "body": "<h2>Results: Polymer-X TGA Run</h2>
   <table>
     <tr><td>Tg</td><td>125.3 °C</td></tr>
     <tr><td>Residue</td><td>2.1%</td></tr>
     ...
   </table>
   <img src='data:image/svg+xml;base64,...' />",
  "metadata": {
    "nomad_url": "https://researchmcp.duckdns.org/nomad-oasis/...",
    "nomad_results": {
      "tg_celsius": 125.3,
      "residue_pct": 2.1,
      ...
    }
  }
}
```

### 5b. Attach Processed Files

Processed data files are uploaded as experiment attachments:
- Cleaned/annotated CSV
- Summary plot SVG
- NOMAD entry export (JSON)

### 5c. Set Status to "Success"

The experiment status is changed to **"Success"** (status ID 71/123).

---

## Phase 6: Review Results (User)

### 6a. Open Experiment

The user opens their elabFTW experiment and sees:
- **Body**: Result summary table + chart (inline)
- **Metadata**: Structured results (Tg, residue, etc.) and NOMAD URL
- **Attachments**: Processed data files

### 6b. Open NOMAD Entry (Optional)

Clicking the NOMAD URL opens the full structured entry with:
- All raw curves (downloadable)
- Complete metadata in NOMAD schema format
- DOI-ready for citation
- Shareable with collaborators (even if they don't have elabFTW access)

---

## Supported Instruments

| Instrument | Template ID | Item ID | Export Format | Parser |
|------------|-------------|---------|---------------|--------|
| TGA | 175 | 1367 | CSV/TXT | TGA parser (temperature, weight, DTG) |
| DMA | 176 | 1368 | CSV/TXT | DMA parser (storage/loss modulus, tan delta) |
| FTIR | 177 | 1369 | DAT | FTIR parser (wavenumber/absorbance) |
| MS | 178 | 1370 | TXT | MS parser (m/z spectrum, TIC) |

## Statuses (eConversion DataIntelligence)

| ID | Title | Default |
|----|-------|---------|
| 70 | Running | Yes |
| 71 | Success | No |
| 122 | Running | Yes |
| 123 | Success | No |
| 124 | Need to be redone | No |
| 125 | Fail | No |
| 126 | Planning | No |
