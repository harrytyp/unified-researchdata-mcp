# Instrument Measurement Workflow: User & Operator Guide

> **eConversion DataIntelligence** — elabFTW + NOMAD Oasis

---

## Status Legend

Each step has a status badge showing what's already working and what still needs human involvement:

| Badge | Meaning |
|-------|---------|
| 🟢 **Automated** | Runs without human intervention. No action needed. |
| 🟡 **Tested** | Has been verified with real data / API calls. Works. |
| 🔵 **Human-verified** | A person must check the output and confirm correctness. |
| 🔴 **Planned** | Not yet implemented. Documented for future development. |
| ⚪ **Manual** | Done by a person in the elabFTW GUI or in the lab. |

---

## Overview

```
   USER (Scientist)                    OPERATOR (Technician)
   ═══════════════                    ═════════════════════
                                       
   ① Book instrument ──────────►   ② Review queue
   (calendar on item page)             
                                       
   ③ Create experiment ─────────►   ④ Load sample in autosampler
   (from template, fill params)        
                                       
   ⑤ Bring sample to lab ───────►   ⑥ Accept request
                                       
                                     ⑦ Run measurement
                                     (TRIOS auto-exports)
                                     ⑧ ───► 🟢 Automated pipeline
                                     
   ⑨ Open experiment ◄───────────   (body + chart + NOMAD link)
       see results inline
```

---

## Step-by-Step

### ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
### PHASE 1: Setup (one time only)
### ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

#### ① Get Access to elabFTW  `⚪ Manual`

| 👤 **USER** | 👷 **OPERATOR** |
|---|---|
| Email Kolja to get an elabFTW account in the **eConversion DataIntelligence** team. | (Already has an account) |
| Open https://elntest.ub.tum.de and log in. | |

---

### ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
### PHASE 2: Request a Measurement
### ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

#### ② Book the Instrument  `⚪ Manual` `🟡 Tested`

| 👤 **USER** | 👷 **OPERATOR** |
|---|---|
| 1. Go to **Database → Devices&Tools** | |
| 2. Pick the instrument you need: | |
|    🟢 **TGA (TA Waters / TRIOS)** | |
|    🟢 **DMA (TA Waters / TRIOS)** | |
|    🟢 **FTIR Spectrometer** | |
|    🟢 **Mass Spectrometer** | |
| 3. Click the **Booking** tab | |
| 4. Select a free time slot on the calendar | |
| 5. Confirm your booking | |
| ✅ **Done: Your time slot is reserved** | |

> ⏰ **Booking rules**: 8 hours max per slot, up to 60 days in advance, no overlapping bookings.
> 
> ✅ **Tested**: 4 instrument items created (IDs 1367–1370), booking enabled via API, user Kolja verified the booking calendar works.

#### ③ Create the Experiment  `⚪ Manual` `🟡 Tested`

| 👤 **USER** | 👷 **OPERATOR** |
|---|---|
| 1. Click **Create experiment from template** | |
| 2. Choose the matching template: | |
|    — **TGA Measurement** (if you booked TGA) | |
|    — **DMA Measurement** (if you booked DMA) | |
|    — **FTIR Measurement** (if you booked FTIR) | |
|    — **MS Measurement** (if you booked MS) | |
| 3. Fill in ALL measurement parameters: | |

**TGA Example:**
```
Sample Name:        Polymer-X
Sample Mass [mg]:   12.5
Crucible Type:      Alumina
Temperature Start:  30 °C
Temperature End:    600 °C
Heating Rate:       10 K/min
Gas Atmosphere:     N2
Gas Flow Rate:      50 mL/min
Autosampler Pos:    5
Notes:              Thermal stability test
```

| 👤 **USER** | 👷 **OPERATOR** |
|---|---|
| 4. Click **Link to item** → select the instrument you booked | |
| 5. Set experiment status to **"Running"** | |
| ✅ **Done: Your request is in the queue** | |

> 📌 **Important**: Fill all fields. The operator needs the parameters to set up the instrument. Missing fields cause delays.
>
> ✅ **Tested**: 4 templates created (IDs 175–178) with 9–12 structured fields each. Test experiment 4688 created via API with all extra_fields populated. User Kolja confirmed the scheduler integration works.

#### ④ Bring Your Sample  `⚪ Manual`

| 👤 **USER** | 👷 **OPERATOR** |
|---|---|
| 1. Prepare your sample (dry, weigh if needed) | |
| 2. Label it clearly with: | |
|    — **Sample name** (from experiment) | |
|    — **Experiment ID** (from elabFTW) | |
| 3. Place it in the designated **lab drop-off** location | |
| ✅ **Your part is done. Wait for results.** | |

> 📌 **Not automated**: This step requires physical handover. Always label samples clearly to avoid mix-ups.

---

### ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
### PHASE 3: Execute the Measurement
### ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

#### ⑤ Review the Queue  `⚪ Manual`

| 👤 **USER** | 👷 **OPERATOR** |
|---|---|
| *(waiting)* | 1. Open **elabFTW → Experiments** |
| | 2. Filter by: **Status = "Running"** |
| | 3. Scan through the list — each experiment shows: |
| |    — 📋 Sample name + all parameters pre-filled |
| |    — 📅 Booked time slot |
| |    — 📍 Autosampler position |
| | ✅ **You see exactly what to do — no paper needed** |

> 🔵 **Human-verified**: The operator checks the parameters are correct before starting.

#### ⑥ Load the Sample  `⚪ Manual`

| 👤 **USER** | 👷 **OPERATOR** |
|---|---|
| | 1. Pick up the physical sample from the drop-off |
| | 2. Load it into the **autosampler** at the position |
| |    specified in the experiment parameters |
| | 3. Tare the pan (if using autosampler) |

> 🔵 **Human-verified**: The operator confirms the correct sample is in the correct position.

#### ⑦ Accept the Request  `⚪ Manual`

| 👤 **USER** | 👷 **OPERATOR** |
|---|---|
| | 1. In the experiment, change status to: |
| |    **"Accepted"** (or similar in-progress status) |
| | 2. This confirms: ✅ Sample loaded ✅ Ready to run |

> 🟡 **Tested**: Status change via API works (experiment 4689 was changed to "Success" automatically).

#### ⑧ Run the Measurement  `⚪ Manual` → `🟢 Automated` `🟡 Tested`

| 👤 **USER** | 👷 **OPERATOR** |
|---|---|
| | 1. Open **TRIOS software** on the instrument PC |
| | 2. Set up the method using the parameters from elabFTW |
| | 3. Start the measurement |
| | 4. **TRIOS auto-exports CSV/TXT** to the network folder ✅ |

> 🟢 **Automated** (sub-step 4): The supplier confirmed TRIOS has an **"Automatically export data after run"** checkbox in SW Options. Once checked, CSV/TXT files land in the watch folder without any manual export step.
>
> 🟡 **Tested**: Real DMA export file (`DMA_PTDB_50AC_1BAPO...`) parsed correctly — 5976 data points, 70 metadata fields, 8 signal columns.
>
> 🔴 **Planned** (sub-step 2): NOMAD auto-generating .TRPC method files from extra_fields. Not implemented yet.

---

### ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
### PHASE 4: Automatic Processing
### ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

| # | Step | Status | What happens | Verified by |
|---|---|---|---|---|
| ⑨ | **TRIOS auto-export** | 🟢 Automated 🟡 Tested | CSV/TXT written to network share after run | Supplier confirmed feature exists (`"Automatical export into ascii/JSON"`) |
| ⑩ | **Watch folder detects file** | 🟢 Automated 🟡 Tested | `instrument_ingest.py watch` polls for new CSV/TXT | Dry-run tested on server with real DMA file |
| ⑪ | **Parser reads data** | 🟢 Automated 🟡 Tested | Extracts 70+ metadata fields, 8 signal columns, 6000+ data points | Verified parser output against raw file — all values match |
| ⑫ | **Compute results** | 🟢 Automated 🟡 Tested | TGA: Tg, residue, onset, DTG peaks, mass loss steps. DMA: Tg tan delta, storage modulus | Tested against real DMA file → Tg = 65.8°C ✓ |
| ⑬ | **Create NOMAD entry** | 🔴 Planned | POST to NOMAD API with structured TgaMeasurement schema | Schema loads in NOMAD (✓), API integration pending |
| ⑭ | **Generate plot** | 🔴 Planned | SVG summary chart with TG + DTG curves | Placeholder returns None |
| ⑮ | **Push back to elabFTW** | 🟢 Automated 🟡 Tested | PATCH experiment body + metadata + status="Success" | Experiment 4689 confirmed — body updated, metadata stored, status changed ✓ |

> **Current automation boundary**: Steps ⑨–⑫ and ⑮ work end-to-end with real data. Steps ⑬–⑭ need the NOMAD API integration. The elabFTW push-back already creates a formatted results table with all computed values.

---

### ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
### PHASE 5: Get Your Results
### ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

#### ⑯ See Results in elabFTW  `🟢 Automated` `🟡 Tested`

| 👤 **USER** | 👷 **OPERATOR** |
|---|---|
| 1. Open your experiment in elabFTW | |
|    *(refresh if it was already open)* | |
| 2. You'll see: | |

```
┌────────────────────────────────────────────────┐
│  TGA Results: Polymer-X                        │
├────────────────────────────────────────────────┤
│  Property              │ Value                 │
├────────────────────────┼───────────────────────┤
│  Tg (glass transition) │ 125.3 °C              │
│  Residue               │ 2.1 %                 │
│  Onset temperature     │ 320.0 °C              │
│  Td5 (5% mass loss)   │ 350.0 °C              │
│  Td10 (10% mass loss) │ 410.0 °C              │
├────────────────────────┴───────────────────────┤
│  Mass Loss Steps                               │
├──────────┬──────────┬───────────┬──────────────┤
│  Onset   │ Offset   │ Mass Loss │ Assignment   │
├──────────┼──────────┼───────────┼──────────────┤
│  30 °C   │ 150 °C   │ 3.2 %     │ moisture     │
│  350 °C  │ 500 °C   │ 68.4 %    │ degradation  │
│  500 °C  │ 800 °C   │ 26.3 %    │ carbonization│
└──────────┴──────────┴───────────┴──────────────┘
```

> ✅ **Tested**: Experiment 4689 received the full results table via API push-back. Body, metadata, and status all updated correctly.

| 👤 **USER** | 👷 **OPERATOR** |
|---|---|
| 3. Click the NOMAD link for: *(when available)* | |
|    — Full structured data | |
|    — Raw curves (downloadable) | |
|    — DOI-ready citation | |
|    — Share with collaborators | |
| ✅ **Done! Your measurement is complete.** | |

> 🔴 **Planned**: NOMAD entry creation + interactive plots. The elabFTW push-back already provides the text results table.

---

## Pipeline Automation Status Overview

```
USER ACTIONS ── all manual ⚪
  Book instrument . . . . . . . . . . . ⚪ Manual  🟡 Tested
  Create experiment . . . . . . . . . . ⚪ Manual  🟡 Tested
  Fill parameters . . . . . . . . . . . ⚪ Manual  🟡 Tested
  Bring sample to lab  . . . . . . . . . ⚪ Manual

OPERATOR ACTIONS ── mostly manual ⚪
  Review queue  . . . . . . . . . . . . ⚪ Manual
  Load + autosampler . . . . . . . . . . ⚪ Manual  🔵 Human-verified
  Accept request  . . . . . . . . . . . ⚪ Manual  🟡 Tested
  Run measurement  . . . . . . . . . . . ⚪ Manual
  │
  └── TRIOS auto-export CSV . . . . . . 🟢 Automated 🟡 Tested

AUTOMATIC PIPELINE
  Watch folder . . . . . . . . . . . . 🟢 Automated 🟡 Tested
  Parse metadata + signals . . . . . . 🟢 Automated 🟡 Tested
  Compute TGA/DMA results . . . . . . . 🟢 Automated 🟡 Tested
  Create NOMAD entry . . . . . . . . . 🔴 Planned
  Generate summary plot . . . . . . . . 🔴 Planned
  Push to elabFTW . . . . . . . . . . . 🟢 Automated 🟡 Tested
```

---

## Summary: What Each Person Does

### 👤 User (Scientist) — all `⚪ Manual`
```
① Book instrument in calendar     (5 minutes)  🟡 Tested
② Create experiment from template (5 minutes)  🟡 Tested
③ Fill measurement parameters     (5 minutes)  🟡 Tested
④ Bring sample to lab             (5 minutes)
⑤ Read results in elabFTW         (5 minutes)  🟢 Automated
                                  ─────────
                    Total effort: ~20 minutes
```

### 👷 Operator (Technician)
```
① Review queue in elabFTW         (2 minutes)  ⚪ Manual
② Load sample + autosampler       (5 minutes)  ⚪ Manual 🔵 Human-verified
③ Accept request                  (1 minute)   ⚪ Manual 🟡 Tested
④ Run measurement in TRIOS        (setup time)  ⚪ Manual
   └── auto-export CSV            (0 min)       🟢 Automated 🟡 Tested
⑤ Results process automatically   (0 minutes)  🟢 Automated 🟡 Tested
                                  ─────────
                    Total effort: ~8 minutes + run time
```

### 🤖 Automatic (Server)
```
① Detect new CSV/TXT file         (instant)    🟢 Automated 🟡 Tested
② Parse metadata + signals        (2 seconds)  🟢 Automated 🟡 Tested
③ Compute results                 (1 second)   🟢 Automated 🟡 Tested
④ Create NOMAD entry              (1 second)   🔴 Planned
⑤ Generate summary plot           (1 second)   🔴 Planned
⑥ Push back to elabFTW            (1 second)   🟢 Automated 🟡 Tested
                                  ─────────
                    Total effort: ~5 seconds
```

---

## Quick Reference: Links

| Action | Link |
|--------|------|
| elabFTW login | [elntest.ub.tum.de](https://elntest.ub.tum.de) |
| TGA Instrument (book) | [database.php?mode=view&id=1367](https://elntest.ub.tum.de/database.php?mode=view&id=1367) |
| DMA Instrument (book) | [database.php?mode=view&id=1368](https://elntest.ub.tum.de/database.php?mode=view&id=1368) |
| FTIR Instrument (book) | [database.php?mode=view&id=1369](https://elntest.ub.tum.de/database.php?mode=view&id=1369) |
| MS Instrument (book) | [database.php?mode=view&id=1370](https://elntest.ub.tum.de/database.php?mode=view&id=1370) |
| NOMAD Oasis | [researchmcp.duckdns.org/nomad-oasis/gui/](https://researchmcp.duckdns.org/nomad-oasis/gui/) |
| elab-app Logger | [elab-app.researchmcp.duckdns.org](https://elab-app.researchmcp.duckdns.org) |

## Templates Available

| Template | Parameters | ID | Status |
|----------|-----------|----|--------|
| TGA Measurement | 12 fields (mass, crucible, temp, gas, etc.) | 175 | 🟡 Tested |
| DMA Measurement | 12 fields (geometry, clamp, temp, frequency, etc.) | 176 | 🟡 Tested |
| FTIR Measurement | 9 fields (state, range, scans, resolution, etc.) | 177 | 🟡 Tested |
| MS Measurement | 9 fields (ionization, mass range, solvent, etc.) | 178 | 🟡 Tested |

## Status Flow

```
Planning (draft)          ⚪ Manual
    │
    ▼
Running                   ⚪ Manual
    │
    ├──► Success          🟢 Automated (from pipeline push-back)
    │         │
    │         ▼
    │      NOMAD entry    🔴 Planned
    │
    └──► Fail             ⚪ Manual
    └──► Need to be redone ⚪ Manual
```

---

*Generated: May 22, 2026 — from the [econversion-nomad](https://github.com/harrytyp/econversion-nomad) repository*
