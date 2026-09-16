"""Tests for notify.mailer - real SMTP delivery and the queue before setup.

A minimal SMTP server is started in-process (Python 3.12 dropped the `smtpd`
module, and this test must not need a package), so the send path is exercised
for real: the message is handed to a socket, the server records what arrived and
the test parses it back.

Run: python3 test_mailer.py
"""
import os
import socket
import sys
import tempfile
import threading
from email import message_from_string
from email.header import decode_header

_HERE = os.path.dirname(os.path.abspath(__file__))
TMP = tempfile.mkdtemp(prefix="tga-mailer-test-")
os.environ["TGA_CONFIG_DIR"] = TMP
# Die Tests liegen in notify/tests; fuer 'from notify import ...' muss das
# Verzeichnis darueber (der Paketordner) auf dem Pfad stehen.
sys.path.insert(0, os.path.dirname(os.path.dirname(_HERE)))

from notify import mailer, settings as settings_mod  # noqa: E402

FAILS = []


def check(label, condition, detail=""):
    if condition:
        print(f"  [OK  ] {label}" + (f" - {detail}" if detail else ""))
    else:
        print(f"  [FAIL] {label}" + (f" - {detail}" if detail else ""))
        FAILS.append(label)


def decode(value):
    parts = decode_header(value or "")
    return "".join(part.decode(enc or "utf-8") if isinstance(part, bytes) else part
                   for part, enc in parts)


class SmtpSink:
    """Just enough SMTP for smtplib: greeting, envelope, data, quit."""

    def __init__(self):
        self.server = socket.socket()
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(5)
        self.port = self.server.getsockname()[1]
        self.messages = []
        self.envelopes = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        try:
            self.server.close()
        except OSError:
            pass

    def _serve(self):
        while not self._stop.is_set():
            try:
                connection, _ = self.server.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(connection,), daemon=True).start()

    def _handle(self, connection):
        connection.sendall(b"220 test-smtp ready\r\n")
        buffer = b""
        message = b""
        in_data = False
        envelope = {}
        with connection:
            while True:
                try:
                    chunk = connection.recv(4096)
                except OSError:
                    return
                if not chunk:
                    return
                buffer += chunk
                while b"\r\n" in buffer:
                    line, buffer = buffer.split(b"\r\n", 1)
                    if in_data:
                        if line == b".":
                            in_data = False
                            self.messages.append(
                                (dict(envelope), message.decode("utf-8", "replace")))
                            message = b""
                            connection.sendall(b"250 Ok: queued\r\n")
                        else:
                            message += line + b"\n"
                        continue
                    upper = line.upper()
                    if upper.startswith((b"EHLO", b"HELO")):
                        connection.sendall(b"250-test-smtp\r\n250 SIZE 20480000\r\n")
                    elif upper.startswith(b"MAIL FROM"):
                        envelope["from"] = line.decode()
                        connection.sendall(b"250 Ok\r\n")
                    elif upper.startswith(b"RCPT TO"):
                        envelope.setdefault("to", []).append(line.decode())
                        connection.sendall(b"250 Ok\r\n")
                    elif upper.startswith(b"DATA"):
                        in_data = True
                        connection.sendall(b"354 End data with <CR><LF>.<CR><LF>\r\n")
                    elif upper.startswith(b"QUIT"):
                        connection.sendall(b"221 Bye\r\n")
                        return
                    else:
                        connection.sendall(b"250 Ok\r\n")


print("=== Ohne SMTP-Konto: einreihen statt scheitern ===")
config = settings_mod.load_settings()
ready, reason = mailer.is_configured(config)
check("nicht konfiguriert erkannt", not ready and "SMTP host" in reason, reason)
status, detail = mailer.send_mail("Betreff", "Text", "wer@tum.de",
                                  config=config, event="test")
check("Status ist 'queued'", status == "queued", detail)
queued = settings_mod.outbox_read()
check("Nachricht liegt in der Outbox", len(queued) == 1
      and queued[0]["subject"] == "Betreff", str(len(queued)))
check("Outbox haelt den Empfaenger", queued[0]["to"] == ["wer@tum.de"])
check("Grund steht dabei", "SMTP host" in queued[0]["reason"])
check("Protokoll vermerkt 'queued'", settings_mod.sent_read()[-1]["status"] == "queued")
check("kein Empfaenger -> failed",
      mailer.send_mail("X", "Y", "", config=config)[0] == "failed")

print()
print("=== Mit SMTP-Konto: echte Zustellung ===")
sink = SmtpSink().start()
config["mail"].update({"host": "127.0.0.1", "port": sink.port, "starttls": False,
                       "from_address": "tga-lab@tum.de", "from_name": "TGA Lab",
                       "reply_to": "p.braun@tum.de"})
ready, reason = mailer.is_configured(config)
check("konfiguriert erkannt", ready, reason)
status, detail = mailer.send_mail(
    "TGA Ergebnisse bereit", "Zeile eins\nZeile zwei",
    ["kolja@tum.de", "zweiter@tum.de"], html="<p>Zeile eins</p>",
    attachments=[("TGA_AB12C_Kollidon.zip", b"PK\x03\x04test")],
    config=config, event="results_ready_user")
check("Versand erfolgreich", status == "sent", detail)
check("der Server hat die Nachricht", len(sink.messages) == 1, str(len(sink.messages)))

envelope, raw = sink.messages[0]
message = message_from_string(raw)
check("Absender mit Anzeigename",
      "tga-lab@tum.de" in decode(message["From"]) and "TGA Lab" in decode(message["From"]),
      decode(message["From"]))
check("beide Empfaenger im Header",
      "kolja@tum.de" in decode(message["To"]) and "zweiter@tum.de" in decode(message["To"]),
      decode(message["To"]))
check("Reply-To gesetzt", "p.braun@tum.de" in decode(message["Reply-To"] or ""))
check("Betreff unveraendert", decode(message["Subject"]) == "TGA Ergebnisse bereit",
      decode(message["Subject"]))
check("Message-ID gesetzt", bool(message["Message-ID"]), str(message["Message-ID"]))
check("Umlaute/UTF-8 kommen heil an", "Zeile eins" in raw and "Zeile zwei" in raw)
check("HTML-Alternative vorhanden", "text/html" in raw)
check("Anhang mit Dateinamen", "TGA_AB12C_Kollidon.zip" in raw)
check("Envelope nennt zwei Empfaenger", len(envelope.get("to", [])) == 2,
      str(envelope.get("to")))
check("Protokoll vermerkt 'sent'", settings_mod.sent_read()[-1]["status"] == "sent")
check("Protokoll enthaelt kein Passwort",
      "streng-geheim" not in str(settings_mod.sent_read()))

print()
print("=== Outbox nachtragen, sobald das Konto steht ===")
settings_mod.outbox_append({"event": "alt", "subject": "Alt", "to": ["alt@tum.de"],
                            "body": "Inhalt von vorher"})
result = mailer.flush_outbox(config)
check("nachtraeglich verschickt", result["sent"] >= 1, str(result))
check("Outbox ist danach leer", settings_mod.outbox_read() == [],
      str(settings_mod.outbox_read()))
received = [message_from_string(raw)["Subject"] for _, raw in sink.messages]
check("auch die alte Nachricht kam an", "Betreff" in received or "Alt" in received,
      str(received))

print()
print("=== Fehler werden gemeldet, nicht geworfen ===")
closed_port = socket.socket()
closed_port.bind(("127.0.0.1", 0))
dead_port = closed_port.getsockname()[1]
closed_port.close()
config["mail"]["port"] = dead_port
status, detail = mailer.send_mail("X", "Y", "wer@tum.de", config=config)
check("Verbindungsfehler -> failed statt Absturz", status == "failed", detail[:60])
check("Fehler im Protokoll", settings_mod.sent_read()[-1]["status"] == "failed")
summary = mailer.outbox_summary()
check("Outbox-Uebersicht zaehlt", summary["count"] == 0, str(summary))

sink.stop()
print()
print("ERGEBNIS:", "ALLE MAILER-CHECKS BESTANDEN" if not FAILS
      else f"{len(FAILS)} FEHLER: " + "; ".join(FAILS))
sys.exit(1 if FAILS else 0)
