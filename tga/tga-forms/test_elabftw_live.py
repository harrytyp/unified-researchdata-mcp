"""Live check against a real eLabFTW: does the export land in the chosen team?

Only runs when the environment carries a key:

    ELABFTW_LIVE_KEY   API key (never in the repository)
    ELABFTW_LIVE_URL   instance, default https://elabftw.researchmcp.duckdns.org
    ELABFTW_LIVE_TEAM  team that the experiment must end up in (default 1)

An experiment is created and deleted again, so a run leaves nothing behind.
"""
import os
import sys

sys.path.insert(0, "/app")

from notify import elabftw  # noqa: E402

KEY = os.environ.get("ELABFTW_LIVE_KEY", "").strip()
URL = os.environ.get("ELABFTW_LIVE_URL", "https://elabftw.researchmcp.duckdns.org").strip()
TEAM = os.environ.get("ELABFTW_LIVE_TEAM", "1").strip()
FAILS = []


def check(label, condition, detail=""):
    print(f"  [{'OK  ' if condition else 'FAIL'}] {label}"
          + (f" - {detail}" if detail else ""))
    if not condition:
        FAILS.append(label)


if not KEY:
    print("ELABFTW_LIVE_KEY ist nicht gesetzt - Live-Test uebersprungen.")
    sys.exit(0)

ctx = {"code": "LIVE1", "sample_name": "Live team check",
       "upload_url": "https://example.invalid/upload/live",
       "parameters": {"atmosphere": "Nitrogen", "sample_mass": "10 mg"},
       "results": {"td5": "300 °C"}}

client = elabftw.ElabFTWClient(URL, KEY, team="")
print(f"Instanz: {client.web_base}  |  Ziel-Team: {TEAM}")

teams = client.teams()
check("Teams des Keys lesbar", bool(teams), str([t.get("id") for t in teams]))
check(f"Ziel-Team {TEAM} ist unter den Teams des Keys",
      any(str(t.get("id")) == TEAM for t in teams), str(teams))

report = elabftw.export_entry(ctx, {"instance_url": URL, "api_key": KEY, "team": TEAM})
check("Export erfolgreich", report["ok"], report["error"])
check("Experiment-ID vorhanden", bool(report["id"]), report["id"])
check("Link vorhanden", report["url"].endswith(report["id"]), report["url"])
check("Team wurde gesetzt", report.get("team_moved") is True,
      str(report.get("team_error")))
check("Bericht nennt das Team", report.get("team") == TEAM, str(report.get("team")))

if report["id"]:
    status, data = None, {}
    import requests
    response = requests.get(f"{client.api_base}/experiments/{report['id']}",
                            headers={"Authorization": KEY}, timeout=30)
    status, data = response.status_code, (response.json() if response.content else {})
    check("Nachfrage: Experiment liegt im Ziel-Team",
          str(data.get("team")) == TEAM, f"team={data.get('team')}")
    check("Nachfrage: Titel nennt die Kennung",
          "LIVE1" in str(data.get("title")), str(data.get("title")))

    delete = requests.delete(f"{client.api_base}/experiments/{report['id']}",
                             headers={"Authorization": KEY}, timeout=30)
    check("Test-Experiment wieder geloescht", delete.status_code < 400,
          f"HTTP {delete.status_code}")

print()
print("ERGEBNIS:", "LIVE-CHECKS BESTANDEN" if not FAILS
      else f"{len(FAILS)} FEHLER: " + "; ".join(FAILS))
sys.exit(1 if FAILS else 0)
