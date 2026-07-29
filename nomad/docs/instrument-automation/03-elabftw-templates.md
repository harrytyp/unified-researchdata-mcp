# elabFTW Setup: Instrument Items, Experiment Templates, Booking

All resources are in the **eConversion DataIntelligence** team (team 29) on
elntest.ub.tum.de.

## Bookable Instrument Items

Four resources created in the **Devices&Tools** category (ID 128):

| Instrument | Item ID | Tags | Booking Config |
|---|---|---|---|
| TGA (TA Waters / TRIOS) | 1367 | TGA, instrument, eConversion | 8h max, 3 slots, 60d window, no overlaps |
| DMA (TA Waters / TRIOS) | 1368 | DMA, instrument, eConversion | 8h max, 3 slots, 60d window, no overlaps |
| FTIR Spectrometer | 1369 | FTIR, instrument, eConversion | 8h max, 3 slots, 60d window, no overlaps |
| Mass Spectrometer | 1370 | MS, instrument, eConversion | 8h max, 3 slots, 60d window, no overlaps |

### Booking Settings

- `is_bookable: 1` — enabled for scheduling
- `book_max_minutes: 480` — max 8 hours per booking
- `book_max_slots: 3` — max 3 concurrent slots per user
- `book_can_overlap: 0` — no overlapping bookings
- `booking_window_days: 60` — can book up to 60 days in advance
- `book_is_cancellable: 1` — users can cancel
- `canbook_base: 30` — team members can book

### Direct Links

- TGA: https://elntest.ub.tum.de/database.php?mode=view&id=1367
- DMA: https://elntest.ub.tum.de/database.php?mode=view&id=1368
- FTIR: https://elntest.ub.tum.de/database.php?mode=view&id=1369
- MS: https://elntest.ub.tum.de/database.php?mode=view&id=1370

## Experiment Templates

Four experiment templates with structured metadata (extra_fields):

### TGA Measurement (ID 175)

**Tags**: TGA, thermogravimetric analysis, instrument, eConversion

| Field | Type | Options |
|-------|------|---------|
| Sample Name | text | |
| Sample Mass [mg] | number | |
| Crucible Type | select | Alumina, Platinum, Aluminum |
| Temperature Start [°C] | number | |
| Temperature End [°C] | number | |
| Heating Rate [K/min] | number | |
| Gas Atmosphere | select | N2, Air, Ar, Synthetic Air, O2 |
| Gas Flow Rate [mL/min] | number | |
| Operator | text | |
| Autosampler Position | number | |
| Method File (.TRPC) | text | |
| Notes | textarea | |

### DMA Measurement (ID 176)

**Tags**: DMA, dynamic mechanical analysis, instrument, eConversion

| Field | Type | Options |
|-------|------|---------|
| Sample Name | text | |
| Sample Geometry (L×W×T mm) | text | |
| Clamp Type | select | Tension, Dual Cantilever, 3-Point Bending, Compression |
| Temperature Start [°C] | number | |
| Temperature End [°C] | number | |
| Heating Rate [K/min] | number | |
| Frequency [Hz] | number | |
| Strain [%] | number | |
| Force [N] | number | |
| Operator | text | |
| Method File (.TRPC) | text | |
| Notes | textarea | |

### FTIR Measurement (ID 177)

**Tags**: FTIR, infrared spectroscopy, instrument, eConversion

| Field | Type | Options |
|-------|------|---------|
| Sample Name | text | |
| Sample State | select | Solid, Liquid, Gas, Film, Powder |
| Spectral Range Start [cm⁻¹] | number | |
| Spectral Range End [cm⁻¹] | number | |
| Number of Scans | number | |
| Resolution [cm⁻¹] | number | |
| Background File (.SPA/.DAT) | text | |
| Operator | text | |
| Notes | textarea | |

### MS Measurement (ID 178)

**Tags**: MS, mass spectrometry, instrument, eConversion

| Field | Type | Options |
|-------|------|---------|
| Sample Name | text | |
| Ionization Method | select | EI, CI, ESI, MALDI, APCI |
| Mass Range Start [m/z] | number | |
| Mass Range End [m/z] | number | |
| Scan Rate | number | |
| Source Temperature [°C] | number | |
| Solvent | text | |
| Operator | text | |
| Notes | textarea | |

## Template Body Content

Each template includes an HTML body with:
- **Workflow instructions** tailored to the instrument
- **Step-by-step** for the operator (weigh → load → set method → run → export)
- Reference to the corresponding instrument item

## Experiment Statuses (Team 29)

| ID | Title | Default | Purpose in pipeline |
|----|-------|---------|-------------------|
| 70 | Running | Yes | User created experiment, awaiting operator |
| 126 | Planning | No | Experiment in planning/draft |
| 124 | Need to be redone | No | Measurement failed, needs re-run |
| 125 | Fail | No | Measurement failed |
| 123 | Success | No | Measurement complete, data ingested |
| 71 | Success | No | (duplicate of 123) |
| 122 | Running | Yes | (duplicate of 70) |

Recommended flow: **Planning (126) → Running (70) → Success (123)**

## API Access

Write-enabled API key for automation is stored securely in the Hermes agent's
memory and in the server's environment. Contact the admin for access.

> **Security note**: Never commit API keys to the repository. The key is rotated
> periodically and should be treated as a shared secret.
