# Instrument Measurement Automation

End-to-end automation for scientific instruments (TGA, DMA, FTIR, MS) connecting
**elabFTW** (user-facing booking & experiment management) with **NOMAD Oasis** (data
ingestion, parsing, archiving).

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                         USER (Scientist)                              │
│  1. Books instrument time slot on an elabFTW resource item           │
│  2. Creates experiment from instrument template, fills parameters     │
│  3. Brings physical sample to the lab                                │
└──────────────────────────┬───────────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────────┐
│                     OPERATOR / TECHNICIAN                            │
│  4. Reviews request queue — sees all parameters pre-filled           │
│  5. Loads sample into autosampler / instrument                       │
│  6. Accepts the request → TRIOS loads the method file                │
│  7. Runs measurement → .tri file generated                           │
└──────────────────────────┬───────────────────────────────────────────┘
                           │ TRIOS auto-exports CSV/TXT to watch folder
                           ▼
┌──────────────────────────────────────────────────────────────────────┐
│                     NOMAD Oasis (Data Pipeline)                       │
│  8. Watch folder detects new CSV/TXT file                            │
│  9. Parser extracts: temperature, weight, DTG curves                 │
│ 10. Creates structured NOMAD entry (TgaMeasurement, etc.)            │
│ 11. Generates summary graph (SVG)                                    │
│ 12. Pushes results back to elabFTW experiment:                       │
│     - Updates body with result table + chart                         │
│     - Adds structured metadata (Tg, mass loss, residue, etc.)        │
│     - Attaches processed data file                                   │
│     - Sets status → "Success"                                        │
└──────────────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────────┐
│                      USER (Scientist)                                │
│ 13. Opens elabFTW experiment → sees results inline                   │
│ 14. Opens NOMAD link → full structured data, DOI, citable            │
└──────────────────────────────────────────────────────────────────────┘
```

## Documents

| Document | What it covers |
|----------|---------------|
| [USER_GUIDE.md](USER_GUIDE.md) | **Step-by-step for users & operators** — left column = user, right column = operator |
| [01-workflow-overview.md](01-workflow-overview.md) | Complete A-to-Z user & system flow |
| [02-infrastructure.md](02-infrastructure.md) | Server, Docker, Caddy, MCP services |
| [03-elabftw-templates.md](03-elabftw-templates.md) | Resource items, experiment templates, booking |
| [04-elab-app.md](04-elab-app.md) | elab-app Streamlit logger deployment |
| [05-data-pipeline.md](05-data-pipeline.md) | NOMAD parser, watch folder, link-back (to be built) |

## Quick Links

| Service | URL |
|---------|-----|
| elabFTW | [elntest.ub.tum.de](https://elntest.ub.tum.de) |
| NOMAD Oasis | [researchmcp.duckdns.org/nomad-oasis/gui/](https://researchmcp.duckdns.org/nomad-oasis/gui/) |
| elab-app Logger | [elab-app.researchmcp.duckdns.org](https://elab-app.researchmcp.duckdns.org) |
| Landing Page | [researchmcp.duckdns.org](https://researchmcp.duckdns.org) |
| GitHub Repo | [github.com/harrytyp/econversion-nomad](https://github.com/harrytyp/econversion-nomad) |
