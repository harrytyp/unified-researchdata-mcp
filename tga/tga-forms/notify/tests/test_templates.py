"""Tests for the notification texts and the recipient logic.

Checks that every event renders, that the plain-text version carries the facts a
reader needs (the sample code, the drop-off address, the entry link), that the
text is English and free of em dashes (the house style for everything users
see), and that the dispatcher picks the right recipients.

Run: python3 test_templates.py
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
# Die Tests liegen in notify/tests; fuer 'from notify import ...' muss das
# Verzeichnis darueber (der Paketordner) auf dem Pfad stehen.
sys.path.insert(0, os.path.dirname(os.path.dirname(_HERE)))

import tempfile

os.environ["TGA_CONFIG_DIR"] = tempfile.mkdtemp(prefix="tga-templates-test-")

from notify import events, settings as settings_mod, templates  # noqa: E402

FAILS = []


def check(label, condition, detail=""):
    if condition:
        print(f"  [OK  ] {label}" + (f" - {detail}" if detail else ""))
    else:
        print(f"  [FAIL] {label}" + (f" - {detail}" if detail else ""))
        FAILS.append(label)


CTX = {
    "code": "AB12C",
    "sample_name": "Kollidon VA64",
    "requester": "Kolja Knodel",
    "requester_email": "kolja.knodel@tum.de",
    "entry_url": "https://researchmcp.duckdns.org/nomad-oasis/gui/user/uploads/upload/id/AB",
    "upload_url": "https://researchmcp.duckdns.org/nomad-oasis/gui/user/uploads/upload/id/AB",
    "drop_off": "TUM School of Engineering and Design\nBoltzmannstr. 15\n85748 Garching",
    "contacts": {"pedro": "p.braun@tum.de", "luca": "luca.reichert@tum.de"},
    "consultation": ["Metallic sample: needs an alumina crucible"],
    "parameters": {
        "atmosphere": "Nitrogen",
        "gas_flows": "25.0 mL/min sample gas",
        "ms_coupling": "coupled",
        "sample_mass": "12.000 mg",
        "runtime": "1.5 h",
        "segments": [{"start": "", "end": "600.0 °C", "rate": "10.00 °C/min", "hold": ""},
                     {"start": "", "end": "", "rate": "", "hold": "30.0 min"}],
    },
    "results": {"mass_loss": "69.8 %", "td5": "305.2 °C", "residue": "30.2 %",
                "sample_mass": "12.333 mg", "pan": "Platinum HT #3"},
    "elabftw_url": "https://elabftw.researchmcp.duckdns.org/experiments.php?mode=view&id=42",
    "elabftw_instance": "https://elabftw.researchmcp.duckdns.org",
    "download_url": "https://researchmcp.duckdns.org/nomad-oasis/api/tga-forms/eln/AB12C",
}

print("=== Jede Vorlage rendert ===")
rendered = {}
for event, builder in templates.BUILDERS.items():
    subject, text, html = builder(CTX)
    rendered[event] = (subject, text, html)
    check(f"{event}: Betreff und Text vorhanden",
          bool(subject) and len(text) > 80 and bool(html),
          f"{subject!r} ({len(text)} Zeichen)")
    check(f"{event}: kein Em-Dash",
          "\u2014" not in text and "\u2014" not in html and "\u2014" not in subject)
    # Die Fehlervorlage kennt keinen Auftrag, sie nennt die Datei.
    expected = (["X_MEASUREMENT.json", "Kollidon VA64", "unknown file"]
                if event == "processing_failed_operator"
                else ["AB12C", "Kollidon VA64"])
    check(f"{event}: Betreff nennt das Betroffene",
          any(needle in subject for needle in expected), subject)

print()
print("=== Inhalt: was der Leser braucht ===")
_, op_text, _ = rendered["request_created_operator"]
check("Operator: was auf die Probe geschrieben wird",
      "Write this code on the sample and on the crucible" in op_text
      and "AB12C" in op_text)
check("Operator: Parameteruebersicht", "Temperature program" in op_text
      and "10.00 °C/min" in op_text and "Nitrogen" in op_text)
check("Operator: Link zum NOMAD-Eintrag", CTX["entry_url"] in op_text)
check("Operator: Ruecksprache genannt", "alumina crucible" in op_text)
check("Operator: Auftraggeber mit Adresse",
      "kolja.knodel@tum.de" in op_text and "Kolja Knodel" in op_text)

_, user_text, _ = rendered["request_created_user"]
check("Nutzer: Kennung zum Beschriften", "AB12C" in user_text
      and "Write this code on the sample" in user_text)
check("Nutzer: Abgabeort vollstaendig", "Boltzmannstr. 15" in user_text
      and "85748 Garching" in user_text)
check("Nutzer: Kontakte fuer die Absprache",
      "p.braun@tum.de" in user_text and "luca.reichert@tum.de" in user_text)
check("Nutzer: Parameteruebersicht", "Your parameters" in user_text
      and "12.000 mg" in user_text)
check("Nutzer: Link zum Eintrag", CTX["entry_url"] in user_text)

_, ready_text, _ = rendered["results_ready_user"]
check("Ergebnis: Werte stehen drin", "305.2 °C" in ready_text
      and "30.2 %" in ready_text and "69.8 %" in ready_text)
check("Ergebnis: Weg in die ELN erklaert",
      "eLabFTW" in ready_text and "experiments.php?mode=view&id=42" in ready_text)
check("Ergebnis: Download erwaehnt", "download the package" in ready_text.lower())
check("Ergebnis: Link zu NOMAD", CTX["entry_url"] in ready_text)

_, fail_text, _ = templates.processing_failed_operator(
    {"filename": "X_MEASUREMENT.json", "error": "ValueError: bad header",
     "upload_url": "https://example/upload"})
check("Fehler: Datei und Meldung genannt",
      "X_MEASUREMENT.json" in fail_text and "ValueError" in fail_text)

print()
print("=== Fehlende Angaben brechen nicht ab ===")
for event, builder in templates.BUILDERS.items():
    try:
        subject, text, html = builder({"sample_name": "Nur ein Name"})
        ok = bool(subject) and isinstance(text, str)
    except Exception as error:                     # noqa: BLE001
        ok = False
        print(f"    {event}: {type(error).__name__}: {error}")
    check(f"{event}: kommt auch mit fast leeren Daten klar", ok)

print()
print("=== Empfaenger-Logik ===")
config = settings_mod.load_settings()
config["recipients"]["operators"] = ["op1@tum.de", "op2@tum.de"]
check("Operator-Ereignis geht an die Operatoren",
      events.recipients_for("request_created_operator", CTX, config)
      == ["op1@tum.de", "op2@tum.de"])
check("Nutzer-Ereignis geht an die Adresse aus dem Antrag",
      events.recipients_for("request_created_user", CTX, config)
      == ["kolja.knodel@tum.de"])
check("ohne Adresse im Antrag greift der Operatoren-Fallback",
      events.recipients_for("results_ready_user", {"code": "X"}, config)
      == ["op1@tum.de", "op2@tum.de"])
check("Doppelte Adressen werden entfernt",
      events.recipients_for("results_ready_user",
                            {"requester_email": "op1@tum.de"}, config)
      == ["op1@tum.de"])

print()
print("=== Schalter und Zustellung ===")
config = settings_mod.load_settings()
report = events.notify("request_created_user", CTX, config=config)
check("ohne konfiguriertes SMTP wird eingereiht",
      report["status"] == "queued", f'{report["status"]} / {report["detail"]}')
config["notifications"]["request_created_user"] = False
report = events.notify("request_created_user", CTX, config=config)
check("abgeschaltetes Ereignis sendet nicht", report["status"] == "disabled")
report = events.notify("gibt-es-nicht", CTX, config=config)
check("unbekanntes Ereignis wird gemeldet", report["status"] == "unknown-event")
config["notifications"]["request_created_user"] = True
config["recipients"]["operators"] = []
report = events.notify("request_created_operator", CTX, config=config)
check("keine Empfaenger wird gemeldet, nicht verschluckt",
      report["status"] == "no-recipients")

print()
print("ERGEBNIS:", "ALLE TEMPLATE-CHECKS BESTANDEN" if not FAILS
      else f"{len(FAILS)} FEHLER: " + "; ".join(FAILS))
sys.exit(1 if FAILS else 0)
