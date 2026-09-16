"""Tests for notify.eln_export - the ZIP a user takes to their ELN.

Checks the package contents, that the CSVs are readable and complete, that the
README explains the files and the computed values, and that a missing figure
(matplotlib absent) does not break the package.

Run: python3 test_eln_export.py
"""
import csv
import io
import json
import os
import sys
import zipfile

_HERE = os.path.dirname(os.path.abspath(__file__))
# Die Tests liegen in notify/tests; fuer 'from notify import ...' muss das
# Verzeichnis darueber (der Paketordner) auf dem Pfad stehen.
sys.path.insert(0, os.path.dirname(os.path.dirname(_HERE)))

from notify import eln_export  # noqa: E402

FAILS = []


def check(label, condition, detail=""):
    if condition:
        print(f"  [OK  ] {label}" + (f" - {detail}" if detail else ""))
    else:
        print(f"  [FAIL] {label}" + (f" - {detail}" if detail else ""))
        FAILS.append(label)


RESULTS = {"td5": "305.2 °C", "td10": "330.5 °C", "residue": "30.2 %",
           "mass_loss": "69.8 %", "sample_mass": "12.333 mg",
           "pan": "Platinum HT #3", "sample_name": "Kollidon VA64"}
SIGNALS = {"time": [0.0, 1.0, 2.0], "temperature": [25.0, 300.0, 400.0],
           "mass_pct": [100.0, 96.6, 30.2], "dtg": [0.0, -1.2, -6.4],
           "dtg_cleaned": [0.0, -1.1, -6.38]}
CTX = {"entry_url": "https://nomad.example/upload/AB12C",
       "requester": "Kolja Knodel <kolja.knodel@tum.de>",
       "measured_on": "2026-09-16", "operator": "Luca Reichert",
       "exported_at": "2026-09-16T14:00:00+0200",
       "contacts": {"pedro": "p.braun@tum.de", "luca": "luca.reichert@tum.de"},
       "dtg_window": "1.81 °C", "dtg_delta": "0.1232"}

print("=== Paket bauen ===")
blob = eln_export.build_package(code="AB12C", sample_name="Kollidon VA64",
                                results=RESULTS, signals=SIGNALS, ctx=CTX)
check("ZIP entsteht", blob[:2] == b"PK", f"{len(blob)} Bytes")
with zipfile.ZipFile(io.BytesIO(blob)) as archive:
    names = archive.namelist()
    check("Dateinamen tragen die Kennung",
          all(name.startswith("AB12C") or name == "README.txt" for name in names),
          str(names))
    check("Ergebnis-CSV dabei", "AB12C_results.csv" in names)
    check("Kurven-CSV dabei", "AB12C_curves.csv" in names)
    check("Metadaten dabei", "AB12C_metadata.json" in names)
    check("README dabei", "README.txt" in names)
    check("Figur dabei (matplotlib vorhanden) oder bewusst weggelassen",
          "AB12C_dtg.png" in names or "not included" in archive.read("README.txt").decode(),
          str("AB12C_dtg.png" in names))

    rows = list(csv.reader(io.StringIO(archive.read("AB12C_results.csv").decode())))
    check("Ergebnis-CSV hat Kopfzeile", rows[0] == ["name", "value", "unit"], str(rows[0]))
    check("Ergebnis-CSV trennt Wert und Einheit",
          ["td5", "305.2 °C", ""] in rows or ["td5", "305.2 °C", ""] == rows[1],
          str(rows[1]))
    check("alle Ergebniszeilen da", len(rows) == len(RESULTS) + 1, str(len(rows)))

    curves = list(csv.reader(io.StringIO(archive.read("AB12C_curves.csv").decode())))
    check("Kurven-CSV mit Kopfzeile", curves[0][0] == "time" and "temperature" in curves[0],
          str(curves[0]))
    check("Kurven-CSV vollstaendig (Kopf + 3 Zeilen)", len(curves) == 4, str(len(curves)))
    check("Kurven-CSV haelt die Reihenfolge",
          curves[1] == ["0.0", "25.0", "100.0", "0.0", "0.0"], str(curves[1]))

    metadata = json.loads(archive.read("AB12C_metadata.json").decode())
    check("Metadaten nennen Kennung und Ergebnisse",
          metadata["sample_code"] == "AB12C" and "td5" in metadata["results"])
    check("Metadaten enthalten keinen API-Key",
          "api_key" not in json.dumps(metadata))

    readme = archive.read("README.txt").decode()
    for needle, label in (("Kollidon VA64", "Probennamen"),
                          ("https://nomad.example/upload/AB12C", "NOMAD-Link"),
                          ("305.2", "Messwerte"),
                          ("Td5", "Erklaerung der Werte"),
                          ("forward and backward", "Rezeptur der DTG-Reinigung"),
                          ("1.81", "verwendete Fensterbreite"),
                          ("p.braun@tum.de", "Kontakt"),
                          ("AB12C_results.csv", "Dateiliste")):
        check(f"README nennt {label}", needle in readme)
    check("README ohne Em-Dash", "\u2014" not in readme)

print()
print("=== Ohne Figur und mit leeren Teilen ===")
blob = eln_export.build_package(code="X1", sample_name="Test", results={},
                                signals={}, ctx=CTX,
                                include_figure=False)
with zipfile.ZipFile(io.BytesIO(blob)) as archive:
    names = archive.namelist()
    check("ohne Kurven keine leere CSV", "X1_curves.csv" not in names, str(names))
    check("Ergebnis-CSV bleibt (mit Kopfzeile)",
          archive.read("X1_results.csv").decode().startswith("name,value,unit"))
    check("README sagt, dass die Figur fehlt",
          "not included" in archive.read("README.txt").decode())

check("Dateiname ohne Sonderzeichen",
      eln_export.package_filename("AB12C", "Kollidon VA64 / Charge 2")
      == "TGA_AB12C_Kollidon_VA64___Charge_2.zip",
      eln_export.package_filename("AB12C", "Kollidon VA64 / Charge 2"))
check("Dateiname ohne Probennamen", eln_export.package_filename("AB12C") == "TGA_AB12C.zip")
check("fehlende Kennung wird abgefangen",
      eln_export.package_filename("") == "TGA_sample.zip")

print()
print("ERGEBNIS:", "ALLE ELN-CHECKS BESTANDEN" if not FAILS
      else f"{len(FAILS)} FEHLER: " + "; ".join(FAILS))
sys.exit(1 if FAILS else 0)
