"""Render all notification texts with realistic sample data into one file.

For reviewing the wording before the mail account exists. Writes English mail
previews to notify_templates_preview.txt next to this script.
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from notify import templates as tpl   # noqa: E402

CTX = {
    "code": "AB12C",
    "sample_name": "Kollidon VA64",
    "requester": "Kolja Knodel",
    "requester_email": "kolja.knodel@tum.de",
    "entry_url": "https://researchmcp.duckdns.org/nomad-oasis/gui/user/uploads/upload/id/AB12Cxyz",
    "upload_url": "https://researchmcp.duckdns.org/nomad-oasis/gui/user/uploads/upload/id/AB12Cxyz",
    "drop_off": ("TUM School of Engineering and Design\n"
                 "Department of Materials Engineering\n"
                 "Lehrstuhl fuer Werkstoffwissenschaften\n"
                 "Boltzmannstr. 15\n85748 Garching\nMW 2228\n"
                 "after agreeing on a date with Pedro or Luca by email"),
    "contacts": {"pedro": "p.braun@tum.de", "luca": "luca.reichert@tum.de"},
    "consultation": ["Mass spectrometer coupling needs to be agreed on beforehand",
                     "Run time above 1 day"],
    "parameters": {
        "atmosphere": "Nitrogen",
        "gas_flow_rate": "20 mL/min",
        "balance_flow_rate": "10 mL/min",
        "ms_coupling": "yes",
        "sample_mass_mg": 50.0,
        "pan_type": "Platinum HT",
        "pan_number": 3,
        "estimated_runtime_h": 1.6,
        # So liefert es entry_data.parameters(): typisierte Schritte in Reihenfolge
        "segments": [
            {"kind": "ramp", "end_temp": 600, "rate": 10},
            {"kind": "hold", "duration_min": 30},
            {"kind": "sample_flow", "flow_rate": 20},
            {"kind": "balance_flow", "flow_rate": 10},
        ],
    },
    "results": {
        "td5": "305.2 C", "td10": "318.7 C", "residue": "30.1 %",
        "residue_temp": "600 C", "sample_mass_mg": "12.333 mg",
        "pan_type": "Platinum HT", "pan_number": "3", "procedure": "Ramp 600 C 10 K/min",
        "dtg_window": "1.81 C", "dtg_delta": "0.123",
    },
    "elabftw_url": "https://elabftw.researchmcp.duckdns.org/experiments.php?mode=view&id=42",
    "elabftw_instance": "https://elabftw.researchmcp.duckdns.org",
    "requests_url": "https://researchmcp.duckdns.org/requests",
    "download_url": "https://researchmcp.duckdns.org/eln/AB12Cxyz",
    "filename": "Kollidon VA64.json",
    "error": "unsupported column header 'Signal_3'",
    "exported_by": "Kolja Knodel",
}

EVENTS = [
    ("request_created_operator", tpl.request_created_operator),
    ("request_created_user", tpl.request_created_user),
    ("results_ready_user", tpl.results_ready_user),
    ("results_ready_operator", tpl.results_ready_operator),
    ("moved_to_elabftw", tpl.moved_to_elabftw),
    ("processing_failed_operator", tpl.processing_failed_operator),
]

lines = ["Notification texts, as they leave the system",
         "=" * 70,
         "Recipients come from the settings (admin page): the operators list gets",
         "the operator mails, the requester gets the confirmation and the result.",
         "Sample data below; the real texts carry the values of the measurement.", ""]

for name, builder in EVENTS:
    message = builder(CTX)
    lines += ["-" * 70, f"Event: {name}", "-" * 70,
              f"Subject: {message[0]}", "", message[1].rstrip(), ""]

output = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "notify_templates_preview.txt")
io.open(output, "w", encoding="utf-8").write("\n".join(lines))
print(f"geschrieben: {output}  ({len(lines)} Zeilen)")
