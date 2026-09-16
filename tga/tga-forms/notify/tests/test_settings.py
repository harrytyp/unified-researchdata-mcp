"""Tests for notify.settings - configuration, secrets, per-user ELN targets.

Runs against a temporary directory (TGA_CONFIG_DIR), never against a real
configuration. Run: python3 test_settings.py
"""
import json
import os
import shutil
import stat
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp(prefix="tga-settings-test-")
os.environ["TGA_CONFIG_DIR"] = TMP
# Die Tests liegen in notify/tests; fuer 'from notify import ...' muss das
# Verzeichnis darueber (der Paketordner) auf dem Pfad stehen.
sys.path.insert(0, os.path.dirname(os.path.dirname(_HERE)))

from notify import settings as s  # noqa: E402

FAILS = []


def check(label, condition, detail=""):
    if condition:
        print(f"  [OK  ] {label}" + (f" - {detail}" if detail else ""))
    else:
        print(f"  [FAIL] {label}" + (f" - {detail}" if detail else ""))
        FAILS.append(label)


print("=== Standardwerte und Speichern ===")
current = s.load_settings()
check("Standardwerte sind da", current["mail"]["port"] == 587
      and current["notifications"]["results_ready_user"] is True)
check("Portal und Formular sind als Link vorkonfiguriert",
      current["links"]["nomad_base"].startswith("https://"))
saved = s.save_settings({"mail": {"host": "postout.lrz.de", "from_address": "tga@tum.de"}})
check("gespeicherte Werte kommen zurueck",
      saved["mail"]["host"] == "postout.lrz.de", saved["mail"]["host"])
check("nicht genannte Bloecke bleiben erhalten",
      saved["recipients"]["lab_contacts"]["pedro"] == "p.braun@tum.de")
s.save_settings({"recipients": {"operators": ["op1@tum.de", "op2@tum.de"]}})
check("Operatoren-Liste ersetzt statt erweitert",
      s.load_settings()["recipients"]["operators"] == ["op1@tum.de", "op2@tum.de"])

print()
print("=== Geheimnisse ===")
s.save_settings({"mail": {"password": "streng-geheim"},
                 "elabftw": {"api_key": "72-abcdef", "instance_url": "https://elab.example"}})
view = s.public_view()
check("Passwort steht nicht in der Ansicht", view["mail"]["password"] == "")
check("Ansicht sagt, dass eines gesetzt ist", view["mail"]["password_set"] is True)
check("API-Key steht nicht in der Ansicht", view["elabftw"]["api_key"] == "")
check("API-Key als gesetzt markiert", view["elabftw"]["api_key_set"] is True)
check("unverschluesseltes Passwort liegt nur in der Datei",
      json.load(open(s.SETTINGS_FILE))["mail"]["password"] == "streng-geheim")
s.save_settings({"mail": {"host": "postout2.mail.lrz.de"}})
check("leeres Passwort beim Speichern loescht nichts",
      s.load_settings()["mail"]["password"] == "streng-geheim")
s.save_settings({"mail": {"password": "neu"}})
check("neues Passwort ersetzt das alte", s.load_settings()["mail"]["password"] == "neu")
mode = stat.S_IMODE(os.stat(s.SETTINGS_FILE).st_mode)
# Windows kennt keine Unix-Rechte; dort (Testrechner) greift der Modus nicht,
# auf dem Server schon - deshalb nur dort pruefen.
if os.name == "nt":
    print(f"  (Rechtepruefung uebersprungen auf Windows - Modus {oct(mode)})")
else:
    check("Konfigurationsdatei ist nur fuer den Besitzer lesbar", mode == 0o600, oct(mode))

print()
print("=== eLabFTW je Nutzer (Instanz, Team, Key frei waehlbar) ===")
user = {"email": "kolja.knodel@tum.de", "username": "kolja.knodel"}
s.save_settings({"elabftw": {"instance_url": "https://elabftw.researchmcp.duckdns.org",
                             "team": "1", "category": "TGA"}})
target = s.user_elabftw(user)
check("ohne eigene Angabe gilt die Vorgabe",
      target["instance_url"].endswith("duckdns.org") and target["team"] == "1")
s.save_user_elabftw(user, {"instance_url": "https://elntest.ub.tum.de",
                           "api_key": "55-meinkey", "team": "7"})
target = s.user_elabftw(user)
check("eigene Instanz ueberschreibt die Vorgabe",
      target["instance_url"] == "https://elntest.ub.tum.de", target["instance_url"])
check("Kategorie wird geerbt", target["category"] == "TGA")
check("eigenes Team", target["team"] == "7")
s.save_user_elabftw(user, {"team": "9"})
check("leerer API-Key loescht den alten nicht",
      s.user_elabftw(user)["api_key"] == "55-meinkey")
check("anderer Nutzer sieht das nicht",
      s.user_elabftw({"email": "wer@tum.de"}).get("api_key") != "55-meinkey")
try:
    s.save_user_elabftw({}, {"team": "1"})
    raised = False
except ValueError:
    raised = True
check("Nutzer ohne Kennung wird abgewiesen", raised)

print()
print("=== Admin-Zugang ===")
check("Kolja Knodel ist Admin", s.is_admin({"username": "kolja.knodel"}))
check("E-Mail-Variante zaehlt auch", s.is_admin({"email": "kolja.knodel@tum.de"}))
check("Fremde Nutzer nicht", not s.is_admin({"username": "max.mustermann"}))
check("kein Nutzer nicht", not s.is_admin(None))
s.save_settings({"admins": ["kolja.knodel", "zweiter.admin"]})
check("Liste ist erweiterbar", s.is_admin({"username": "zweiter.admin"}))

print()
print("=== Outbox und Protokoll ===")
s.outbox_append({"event": "results_ready_user", "subject": "Test", "to": ["a@b.c"],
                 "body": "Inhalt"})
check("Eintrag in der Outbox", s.outbox_read()[0]["subject"] == "Test")
s.outbox_append({"event": "request_created_user", "subject": "Zweite", "to": ["c@d.e"]})
check("Outbox waechst", len(s.outbox_read()) == 2)
s.outbox_replace(s.outbox_read()[:1])
check("Outbox laesst sich nach dem Versand kuerzen", len(s.outbox_read()) == 1)
s.log_sent({"event": "test", "to": ["a@b.c"], "status": "queued"})
check("Protokoll wird geschrieben", s.sent_read()[0]["status"] == "queued")
check("Protokoll ohne Geheimnisse", "streng-geheim" not in json.dumps(s.sent_read()))

print()
print("=== Merker gegen doppelte Benachrichtigungen ===")
check("noch nichts vermerkt", s.was_notified("UP1") == "")
s.mark_notified("UP1", "2026-09-16T12:00|5")
check("Stand vermerkt", s.was_notified("UP1") == "2026-09-16T12:00|5")
check("anderer Upload bleibt unberuehrt", s.was_notified("UP2") == "")
s.mark_notified("UP1", "neuer Stand")
check("neuer Stand ueberschreibt", s.was_notified("UP1") == "neuer Stand")
check("Merkerdatei ist nicht oeffentlich",
      os.name == "nt" or stat.S_IMODE(os.stat(s.NOTIFIED_FILE).st_mode) == 0o600)

shutil.rmtree(TMP, ignore_errors=True)
print()
print("ERGEBNIS:", "ALLE SETTINGS-CHECKS BESTANDEN" if not FAILS
      else f"{len(FAILS)} FEHLER: " + "; ".join(FAILS))
sys.exit(1 if FAILS else 0)
