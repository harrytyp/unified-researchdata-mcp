"""Tests for notify.elabftw against a stub eLabFTW instance.

The stub speaks the parts of the v2 REST API the export uses and can be told to
behave like an old instance (rejects tags in the create payload, sends the id
only in the Location header) or to refuse (401/403). That covers exactly the
version differences the client has to absorb, without needing a real instance.

Run: python3 test_elabftw.py
"""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_HERE = os.path.dirname(os.path.abspath(__file__))
# Die Tests liegen in notify/tests; fuer 'from notify import ...' muss das
# Verzeichnis darueber (der Paketordner) auf dem Pfad stehen.
sys.path.insert(0, os.path.dirname(os.path.dirname(_HERE)))

from notify import elabftw  # noqa: E402

FAILS = []
KEY = "72-testkey-must-not-leak"


def check(label, condition, detail=""):
    if condition:
        print(f"  [OK  ] {label}" + (f" - {detail}" if detail else ""))
    else:
        print(f"  [FAIL] {label}" + (f" - {detail}" if detail else ""))
        FAILS.append(label)


class Stub:
    """eLabFTW stand-in. modes: 'modern' | 'old' | 'forbidden'."""

    def __init__(self, mode="modern"):
        self.mode = mode
        self.requests = []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def _send(self, status, payload=None, headers=None):
                body = json.dumps(payload or {}).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(body)

            def _record(self, length=0):
                stub.requests.append({
                    "method": self.command,
                    "path": self.path,
                    "auth": self.headers.get("Authorization", ""),
                    "body": self.rfile.read(length) if length else b"",
                })

            def do_GET(self):
                self._record()
                if self.headers.get("Authorization") != KEY:
                    return self._send(401, {"code": 401, "message": "Authentication required"})
                if self.path.startswith("/api/v2/info"):
                    return self._send(200, {"version": "6.0.0-beta2",
                                            "elabftw_version": "6.0.0-beta2"})
                if self.path.startswith("/api/v2/teams"):
                    return self._send(200, [{"id": 1, "name": "Materials"}, {"id": 7, "name": "TGA"}])
                return self._send(404, {"message": "Not found"})

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                stub.requests.append({
                    "method": self.command, "path": self.path,
                    "auth": self.headers.get("Authorization", ""),
                    "body": raw,
                    "content_type": self.headers.get("Content-Type", ""),
                })
                if self.headers.get("Authorization") != KEY:
                    return self._send(401, {"code": 401, "message": "Authentication required"})
                if stub.mode == "forbidden":
                    return self._send(403, {"code": 403, "message": "Not allowed"})

                if self.path.startswith("/api/v2/experiments") and "/uploads" in self.path:
                    return self._send(201, {"id": 1})
                if self.path.startswith("/api/v2/experiments") and "/tags" in self.path:
                    return self._send(201, {"id": 1})

                if self.path.startswith("/api/v2/experiments"):
                    payload = json.loads(raw or b"{}")
                    if stub.mode == "old":
                        if "tags" in payload:
                            return self._send(400, {"message": "Unknown field 'tags'"})
                        return self._send(201, {}, headers={"Location": "/api/v2/experiments/77"})
                    return self._send(201, {"id": 42, "title": payload.get("title")})
                return self._send(404, {"message": "Not found"})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"


print("=== Instanz-URL verstehen ===")
check("ohne Schema wird https",
      elabftw.normalize_instance("elab.example.org")[0] == "https://elab.example.org")
check("mit /api/v2 wird abgeschnitten",
      elabftw.normalize_instance("https://elab.example.org/api/v2/")[1]
      == "https://elab.example.org/api/v2")
check("Unterpfad bleibt erhalten",
      elabftw.normalize_instance("https://host/elab")[1] == "https://host/elab/api/v2")


def raises(fn, kind=Exception):
    try:
        fn()
        return False
    except kind:
        return True


check("leere Angabe wirft", raises(lambda: elabftw.normalize_instance(""), ValueError))
check("fehlender Key wird abgelehnt",
      raises(lambda: elabftw.ElabFTWClient("https://x", ""), elabftw.ElabFTWError))

print()
print("=== Verbindungstest ===")
stub = Stub("modern").start()
client = elabftw.ElabFTWClient(stub.url, KEY)
connection = client.test_connection()
check("Verbindung ok", connection["ok"], connection["error"])
check("Version gelesen", connection["version"] == "6.0.0-beta2", connection["version"])
check("Teams gelesen", len(connection["teams"]) == 2, str(connection["teams"]))
check("Key nur im Header, nie in der URL",
      all(request["auth"] == KEY for request in stub.requests)
      and all(KEY not in request["path"] for request in stub.requests))

bad = elabftw.ElabFTWClient(stub.url, "falscher-key").test_connection()
check("falscher Key wird verstaendlich gemeldet",
      not bad["ok"] and "401" in bad["error"], bad["error"])
offline = elabftw.ElabFTWClient("http://127.0.0.1:9", KEY).test_connection()
check("nicht erreichbare Instanz wird gemeldet",
      not offline["ok"] and offline["error"], offline["error"][:60])

print()
print("=== Experiment anlegen (moderne Instanz) ===")
ctx = {"code": "AB12C", "sample_name": "Kollidon VA64", "requester": "Kolja",
       "entry_url": "https://nomad.example/upload/AB",
       "upload_url": "https://nomad.example/upload/AB",
       "parameters": {"atmosphere": "Nitrogen", "sample_mass": "12.3 mg",
                      "segments": [{"end": "600 °C", "rate": "10 °C/min"}]},
       "results": {"td5": "305.2 °C", "residue": "30.2 %", "pan": "Platinum HT #3"}}
report = elabftw.export_entry(ctx, {"instance_url": stub.url, "api_key": KEY,
                                    "team": "7", "category": "TGA"},
                              figure=b"\x89PNG-fake", filename="dtg.png")
check("Export ok", report["ok"], report["error"])
check("Experiment-ID aus dem Body", report["id"] == "42", report["id"])
check("Link auf das Experiment",
      report["url"].endswith("/experiments.php?mode=view&id=42"), report["url"])
check("Figur angehaengt", report["attached"])
created = next(r for r in stub.requests
               if r["method"] == "POST" and r["path"].startswith("/api/v2/experiments"))
payload = json.loads(created["body"])
check("Titel traegt Kennung und Probennamen",
      "AB12C" in payload["title"] and "Kollidon VA64" in payload["title"], payload["title"])
check("Kategorie gesetzt", payload.get("category") == "TGA")
check("Tags gesetzt", "AB12C" in payload.get("tags", []), str(payload.get("tags")))
check("Team als Query-Parameter", "team=7" in created["path"], created["path"])
check("Body nennt Parameter und Ergebnisse",
      "Nitrogen" in payload["body"] and "305.2" in payload["body"]
      and "Platinum HT #3" in payload["body"])
check("Body verlinkt den NOMAD-Eintrag", "https://nomad.example/upload/AB" in payload["body"])
check("Team/Kategorie/Key stehen nicht im Export-Bericht",
      KEY not in elabftw.export_report_json(report))
stub.stop()

print()
print("=== Alte Instanz: Tags erst separat, ID nur im Location-Header ===")
stub = Stub("old").start()
report = elabftw.export_entry({"code": "C3D4E", "sample_name": "Test"},
                              {"instance_url": stub.url, "api_key": KEY})
check("Export ok", report["ok"], report["error"])
check("ID aus dem Location-Header", report["id"] == "77", report["id"])
tag_calls = [r for r in stub.requests if "/tags" in r["path"]]
check("Tags nachgereicht", len(tag_calls) >= 1, str(len(tag_calls)))
stub.stop()

print()
print("=== Abgelehnt und ohne Schluessel ===")
stub = Stub("forbidden").start()
report = elabftw.export_entry(ctx, {"instance_url": stub.url, "api_key": KEY})
check("403 wird gemeldet statt zu werfen",
      not report["ok"] and "403" in report["error"], report["error"])
stub.stop()
report = elabftw.export_entry(ctx, {"instance_url": "", "api_key": ""})
check("fehlende Angaben werden gemeldet",
      not report["ok"] and "missing" in report["error"], report["error"])

print()
print("=== HTML-Body ===")
body = elabftw.experiment_body({"code": "X<1", "sample_name": "A&B",
                                "parameters": {"segments": []},
                                "results": {}})
check("HTML wird escaped", "&lt;1" in body and "A&amp;B" in body)

print()
print("ERGEBNIS:", "ALLE ELABFTW-CHECKS BESTANDEN" if not FAILS
      else f"{len(FAILS)} FEHLER: " + "; ".join(FAILS))
sys.exit(1 if FAILS else 0)
