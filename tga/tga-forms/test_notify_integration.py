"""End-to-end check of the notification and ELN process, inside the app container.

Covers the chain the user asked for, with the pieces that a browser would drive:

1. a new request notifies operator and requester (queued, because no mail
   account is configured yet) and the texts carry what the readers need,
2. a processed measurement notifies the requester and the operators, with the
   real result values read from the entry archive of the kept E2E upload,
3. the ELN download endpoint answers with a ZIP, and refuses without a session,
4. the eLabFTW export path builds the experiment and attaches the figure
   (against a local stub instance, so no real API key is needed),
5. the admin page is limited to the configured accounts.

The real queue file is backed up and restored, so this test does not leave test
mail behind that would later be flushed for real.

Run: docker exec tga-forms python3 /tmp/test_notify_integration.py [upload_id]
"""
import asyncio
import io
import json
import os
import shutil
import sys
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, '/app')

UP = sys.argv[1] if len(sys.argv) > 1 else 'zLZXI7AAR9KZxq9CDy2XTw'

FAILS = []
from notify import elabftw as elabftw_mod          # noqa: E402
from notify import eln_export, entry_data, events, mailer, settings as settings_mod  # noqa: E402

# Outbox und Protokoll sichern, damit der Test keine Spuren hinterlaesst
BACKUPS = {}
for path in (settings_mod.OUTBOX_FILE, settings_mod.SENT_FILE):
    BACKUPS[path] = path + '.ittest-backup'
    if os.path.exists(path):
        shutil.copy2(path, BACKUPS[path])
    elif os.path.exists(BACKUPS[path]):
        os.remove(BACKUPS[path])


def restore():
    for path, backup in BACKUPS.items():
        try:
            if os.path.exists(backup):
                shutil.copy2(backup, path)
                os.remove(backup)
            elif os.path.exists(path):
                os.remove(path)
        except OSError:
            pass


# Wie viele Eintraege vor dem Test schon in der Warteschlange lagen.
OUTBOX_BEFORE = len(settings_mod.outbox_read())


def check(label, condition, detail=''):
    if condition:
        print(f'  [OK  ] {label}' + (f' - {detail}' if detail else ''))
    else:
        print(f'  [FAIL] {label}' + (f' - {detail}' if detail else ''))
        FAILS.append(label)


if not entry_data.read_fields(UP):
    print(f'Die Anfrage {UP} hat keine Daten (geloescht oder noch nicht '
          f'verarbeitet). Bitte eine aktuelle Upload-ID uebergeben, z.B. aus '
          f'GET /api/v1/uploads.')
    restore()
    sys.exit(2)

print('=== 1. Neuer Antrag: Operator und Auftraggeber werden benachrichtigt ===')
archive = {'data': {
    'm_def': 'instrument_data.schema.TgaMeasurement',
    # Der Antragsteller hat im Formular zugestimmt: nur dann geht die Mail an
    # ihn. Ohne den Haken prueft Abschnitt 1b, dass nichts rausgeht.
    'notify_requester': True,
    'requester_email': 'kolja.knodel@tum.de',
    'gas_atmosphere': 'Nitrogen',
    'gas_flow_rate': 25.0,
    'ms_coupling': True,
    'sample': {'sample_name': 'Kollidon VA64', 'sample_mass': 12.0,
               'operator': 'Luca Reichert'},
    'temperature_segments': [{'m_def': 'instrument_data.schema.RampSegment',
                              'end_temp': 600.0, 'rate': 10.0},
                             {'m_def': 'instrument_data.schema.IsothermalSegment',
                              'duration_min': 30.0}],
}}
import ui_notify  # noqa: E402

reports = ui_notify.notify_new_request('TESTUP1234567890abc', archive,
                                       {'name': 'Kolja Knodel',
                                        'email': 'kolja.knodel@tum.de'},
                                       consultation=['Metallic sample'])
by_event = {r.get('event'): r for r in reports}
check('beide Ereignisse verarbeitet', set(by_event) == {'request_created_operator',
                                                        'request_created_user'},
      str(sorted(by_event)))
# Nur, was dieser Lauf einreiht: in der echten Warteschlange koennen aeltere
# Eintraege liegen (sie wird am Ende wiederhergestellt), und die wurden hier
# vorher mitgezaehlt.
queued = settings_mod.outbox_read()[OUTBOX_BEFORE:]
check('beide Mails liegen in der Warteschlange', len(queued) >= 2, str(len(queued)))
operator_mail = next((q for q in queued if q['event'] == 'request_created_operator'), {})
user_mail = next((q for q in queued if q['event'] == 'request_created_user'), {})
check('Operator-Mails nennen den Proben-Code',
      'TESTU' in operator_mail.get('subject', ''), operator_mail.get('subject', ''))
check('Operator-Mail sagt, was auf die Probe geschrieben wird',
      'crucible' in operator_mail.get('body', ''))
check('Operator-Mail nennt Parameter und Ruecksprache',
      'Temperature program' in operator_mail.get('body', '')
      and 'Metallic sample' in operator_mail.get('body', ''))
check('Auftraggeber-Mail nennt Abgabeort und Kontakte',
      'Boltzmannstr' in user_mail.get('body', '')
      and 'p.braun@tum.de' in user_mail.get('body', ''))
check('Auftraggeber-Mail geht an die Adresse aus dem Antrag',
      user_mail.get('to') == ['kolja.knodel@tum.de'], str(user_mail.get('to')))
check('Operator-Mail nennt die Operatoren-Empfaenger',
      'to' in operator_mail, str(operator_mail.get('to')))

print()
print('=== 1b. Ohne Zustimmung im Antrag keine Mail an den Auftraggeber ===')
probe_ctx = {'code': 'CONS1', 'sample_name': 'Probe', 'requester_email': 'wer@example.org',
             'entry_url': 'https://example.invalid', 'parameters': {'segments': []},
             'results': {}}
plain = events.notify('request_created_user', probe_ctx)
check('ohne Zustimmung: nichts an den Auftraggeber',
      plain['status'] in ('no-recipients', 'disabled'), str(plain))
with_ok = events.notify('request_created_user', dict(probe_ctx, notify_requester=True))
check('mit Zustimmung: die Mail geht raus',
      with_ok['status'] in ('queued', 'sent') and 'wer@example.org' in str(with_ok.get('recipients')),
      str(with_ok))
operator_still = events.notify('request_created_operator', probe_ctx)
check('die Operatoren bekommen ihre Mail unabhaengig davon',
      operator_still['status'] in ('queued', 'sent'), str(operator_still))

print()
print('=== 2. Verarbeitete Messung: Ergebnisse gehen raus ===')
summary = entry_data.request_summary(UP)
check('Eintrag gelesen', bool(summary['results']), str(summary['results']))
asyncio.run(ui_notify._notify_when_ready(UP, '', timeout=20))
after = settings_mod.outbox_read()
new_events = [q['event'] for q in after if q['event'].startswith('results_ready')]
check('Ergebnis-Mails eingereiht', set(new_events) >= {'results_ready_user',
                                                       'results_ready_operator'},
      str(new_events))
ready = next((q for q in reversed(after) if q['event'] == 'results_ready_user'), {})
check('Ergebnis-Mail nennt Werte und NOMAD-Link',
      'NOMAD entry' in ready.get('body', '') and 'upload' in ready.get('body', ''))
check('Ergebnis-Mail erklaert den Weg in die ELN',
      'eLabFTW' in ready.get('body', ''))
# NOMAD verarbeitet denselben Upload mehrfach und meldet jedes Mal: die zweite
# Meldung darf keine neuen Mails erzeugen.
before = len(settings_mod.outbox_read())
asyncio.run(ui_notify._notify_when_ready(UP, '', timeout=20))
after_second = [q for q in settings_mod.outbox_read()[before:]
                if q['event'].startswith('results_ready')]
check('erneute Meldung erzeugt keine zweite Mail', not after_second,
      f'{len(after_second)} neue')

print()
print('=== 3. ELN-Download-Endpunkt ===')
import urllib.request  # noqa: E402


def get(path, cookie=None):
    request = urllib.request.Request('http://127.0.0.1:8090' + path)
    if cookie:
        request.add_header('Cookie', cookie)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, response.read(), dict(response.headers)
    except Exception as error:                                  # noqa: BLE001
        return getattr(error, 'code', 0), b'', {}


status, body, _ = get(f'/eln/{UP}')
check('ohne Session abgelehnt', status == 401, str(status))
status, body, _ = get('/eln/DOES-NOT-EXIST12345')
check('unbekannter Upload abgelehnt', status in (401, 403, 404), str(status))

print()
print('=== 4. eLabFTW-Export (gegen eine Stub-Instanz) ===')
class Stub:
    def __init__(self):
        self.requests = []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def log_message(self, *args):
                pass

            def _send(self, status, payload=None, headers=None):
                blob = json.dumps(payload or {}).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(blob)))
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(blob)

            def do_GET(self):
                if self.headers.get('Authorization') != '77-appkey':
                    return self._send(401, {'message': 'Authentication required'})
                if '/info' in self.path:
                    return self._send(200, {'version': '6.0.0-beta2'})
                return self._send(200, [{'id': 1, 'name': 'Materials'}])

            def do_POST(self):
                length = int(self.headers.get('Content-Length') or 0)
                stub.requests.append((self.path, self.rfile.read(length),
                                      self.headers.get('Authorization', '')))
                if self.headers.get('Authorization') != '77-appkey':
                    return self._send(401, {'message': 'Authentication required'})
                if '/uploads' in self.path:
                    return self._send(201, {'id': 1})
                return self._send(201, {'id': 99})

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


stub = Stub()
target = {'instance_url': f'http://127.0.0.1:{stub.port}', 'api_key': '77-appkey',
          'team': '1', 'category': 'TGA'}
summary = entry_data.request_summary(UP)
row = {'upload_id': UP, 'code': UP[:5], 'sample': summary['sample_name'],
       'created': '2026-09-16', 'gui_url': 'https://example/upload/' + UP}
ctx = ui_notify._export_context(row, summary)
figure = eln_export.dtg_figure(summary['signals'], 'Test')
check('Figur aus den echten Kurven gerendert', figure is not None and figure[:4] == b'\x89PNG',
      f'{len(figure or b"")} Bytes')
report = elabftw_mod.export_entry(ctx, target, figure=figure, filename='dtg.png')
check('Export erfolgreich', report['ok'], report['error'])
check('Experiment-ID und Link da', report['id'] == '99' and 'experiments.php' in report['url'],
      report['url'])
# Der Pfad traegt das Team als Query (?team=1), deshalb nicht auf das Ende matchen.
created = next((payload for path, payload, _ in stub.requests
                if '/experiments' in path and '/uploads' not in path
                and '/tags' not in path), b'{}')
experiment = json.loads(created or b'{}')
check('Experiment enthaelt Kennung, Programm und Ergebnisse',
      experiment.get('title', '').startswith('TGA ')
      and 'Temperature program' in experiment.get('body', '')
      and 'Platinum HT #3' in experiment.get('body', ''))
check('Experiment verlinkt den NOMAD-Eintrag',
      'https://example/upload/' + UP in experiment.get('body', ''))
check('Figur wurde angehaengt', report['attached'])
check('API-Key bleibt im Header', all(auth == '77-appkey' for _, _, auth in stub.requests))
stub.stop()

print()
print('=== 5. Admin-Zugang ===')
check('Admin erlaubt', settings_mod.is_admin({'username': 'kolja.knodel'}))
check('anderer Nutzer nicht erlaubt', not settings_mod.is_admin({'username': 'luca'}))
check('kein Nutzer nicht erlaubt', not settings_mod.is_admin(None))
check('Einstellungen ohne Klartext-Passwort nach aussen',
      settings_mod.public_view()['mail']['password'] == '')

restore()
print()
print('ERGEBNIS:', 'ALLE INTEGRATIONS-CHECKS BESTANDEN' if not FAILS
      else f'{len(FAILS)} FEHLER: ' + '; '.join(FAILS))
sys.exit(1 if FAILS else 0)
