"""Backend smoke test: syntax + core logic with a fake client (no UI, no network)."""
import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp()
os.environ['HOME'] = _tmp
os.environ['USERPROFILE'] = _tmp
sys.path.insert(0, str(Path(__file__).parent))

from backend import Backend, load_config, save_config, slot_filename, STATUSES, procedure_label

class FakeClient:
    def __init__(self):
        self.tprc = b'\tVERSIONED' + b'\x00' * 120
    def list_uploads(self, per_page=100):
        return [
            {'upload_id': 'AAA111', 'upload_name': None, 'upload_create_time': '2026-08-01T10:00:00', 'entries': 1},
            {'upload_id': 'BBB222', 'upload_name': 'MyExp', 'upload_create_time': '2026-08-02T10:00:00', 'entries': 1},
            {'upload_id': 'CCC333', 'upload_name': None, 'upload_create_time': '2026-08-03T10:00:00', 'entries': 1},
        ]
    def list_upload_entries(self, uid):
        base = {'entry_type': 'TgaMeasurement',
                'main_author': {'user_id': 'u1', 'name': 'Kolja Knodel'},
                'data': {'sample': {'sample_name': 'Probe A'},
                         'procedure_name': '10K_min',
                         'temperature_segments': [{'segment_type': 'ramp', 'end_temp': 400, 'rate': 10}]}}
        if uid == 'BBB222':
            base['data']['sample']['sample_name'] = 'Probe B'
            base['data']['procedure_name'] = None
        return [{'entry_metadata': base}]
    def list_raw_files(self, uid):
        if uid == 'AAA111':
            return [{'name': 'Sample.tprc', 'size': 2550, 'is_file': True}]
        if uid == 'BBB222':
            return [{'name': 'Sample.tprc', 'size': 2550, 'is_file': True},
                    {'name': 'result.tri', 'size': 100, 'is_file': True}]
        # CCC333: NO raw files (no .tprc) — used by test 5a
        return []
    def download_raw(self, uid, rel, dest):
        Path(dest).write_bytes(self.tprc)
        return len(self.tprc)
    def upload_raw(self, *a, **k):
        return True
    def trigger_process(self, uid):
        self.triggers = getattr(self, 'triggers', []) + [uid]
        return True
    def get_upload(self, uid):
        return {'process_running': False, 'process_status': 'SUCCESS'}
    def wait_until_idle(self, uid, timeout=180, poll=3):
        return True
    def check_health(self):
        return True, 'ok'

b = Backend(client=FakeClient())
b.on_log = lambda ts, tag, msg: print(f'  [log:{tag}] {msg}')

# 1. Refresh
rows = b.refresh()
assert len(rows) == 3, f'erwartet 3, habe {len(rows)}'
a = [r for r in rows if r['upload_id'] == 'AAA111'][0]
assert a['sample'] == 'Probe A', a['sample']
assert a['procedure'] == '10K_min', a['procedure']
assert a['author'] == 'Kolja Knodel', a['author']
assert a['has_tprc'] and not a['has_tri']
bb = [r for r in rows if r['upload_id'] == 'BBB222'][0]
assert bb['procedure'] == '1 Seg: ramp', f"Fallback procedure: {bb['procedure']}"
assert bb['has_tri']
print('1. Refresh + Metadaten OK (3 Uploads, author/procedure/fallback)')

# 2. Status-Auto: BBB222 hat .tri -> measured
assert b.display_status('BBB222', has_result=True) == 'measured'
assert b.display_status('AAA111', has_result=False) == 'pending'
print('2. Auto-Status OK (BBB measured via .tri, AAA pending)')

# 3. Status setzen + persistieren
b.set_status('AAA111', 'received')
assert b.manual_status('AAA111') == 'received'
cfg = load_config()
assert cfg['sample_status']['AAA111']['status'] == 'received'
print('3. Status setzen + Config-Persistenz OK')

# 4. Slot-Zuweisung + Dateinamen
b.assign_slot('AAA111', '03')
assert b.slot_for('AAA111') == '03'
assert b.display_status('AAA111', has_result=False) == 'assigned'  # Slot -> assigned
assert slot_filename('Probe A', '03', 'AAA111') == 'Probe A_03.tprc'
print('4. Slot-Zuweisung + display_status=assigned OK')

# 5. save_slot_files (lädt .tprc als {Sample}_{Slot}.tprc)
# Slots werden JETZT intern vergeben (atomar mit der Dateiarbeit — kein
# Race mit dem Watcher). Erster freier Slot: 01.
import_dir = Path(_tmp) / 'TRIOS' / 'Methods'
ok, failed = b.save_slot_files([{'upload_id': 'AAA111', 'sample': 'Probe A'}], import_dir)
assert ok and (import_dir / 'Probe A_01.tprc').exists(), f'ok={ok} failed={failed}'
assert b.slot_for('AAA111') == '01', f'Slot muss intern vergeben sein, ist {b.slot_for("AAA111")}'
print(f'5. Slot-Dateien OK: {(import_dir / "Probe A_01.tprc").name} (Slot intern vergeben)')

# 5a. Probe OHNE .tprc darf keinen Slot verbrennen (Bug-Fix: Slots 3-4 statt 1-2)
# CCC333 hat im FakeClient keinen .tprc-Raw-File -> muss fehlschlagen UND Slot 02
# muss für die nächste erfolgreiche Probe frei bleiben.
ok2, failed2 = b.save_slot_files([{'upload_id': 'CCC333', 'sample': 'Probe C'},
                                  {'upload_id': 'BBB222', 'sample': 'Probe B'}], import_dir)
assert len(ok2) == 1 and len(failed2) == 1, f'ok={ok2} failed={failed2}'
assert b.slot_for('BBB222') == '02', f'Probe B muss Slot 02 bekommen (01 nicht verbrannt), ist {b.slot_for("BBB222")}'
assert b.slot_for('CCC333') is None, 'Probe C (ohne tprc) darf keinen Slot haben'
print('5a. Probe ohne .tprc: kein Slot-Verbrauch OK (B -> 02, C -> keiner)')

# 5b. Slot wird bei Statuswechsel auf measured gelöscht (Bug-Fix)
b.assign_slot('BBB222', '05')
assert b.slot_for('BBB222') == '05'
b.set_status('BBB222', 'measured')
assert b.slot_for('BBB222') is None, 'Slot muss bei measured gelöscht werden'
assert b.display_status('BBB222', has_result=True) == 'measured'
print('5b. Slot-Löschung bei measured OK')

# 6. Watcher RESTART-SAFE: Dateien, die VOR App-Start da waren (z.B. TRIOS
# fertig, EXE startet danach), werden beim ersten Tick hochgeladen.
exp = Path(_tmp) / 'TRIOS' / 'Data'
exp.mkdir(parents=True, exist_ok=True)
# 'Probe A_03.tri' liegt schon (wie wenn TRIOS vor der EXE fertig war)
(exp / 'Probe A_01.tri').write_bytes(b'fake tri')
# file_owner wurde beim save_slot_files gesetzt (Probe A_03.tprc -> AAA111)
b.config['auto_upload'] = True
b.watcher_tick()  # erster Tick: MUSS die vorhandene .tri hochladen (kein Skip)
# 'Probe A_01.tri' -> stem 'Probe A_01' -> file_owner['Probe A_03.tprc'] = AAA111
assert b.config.get('uploaded_results', {}).get('Probe A_01.tri'),     'Datei die vor Start da war muss hochgeladen + geloggt werden'
print('6. Restart-sicher: vorhandene .tri beim 1. Tick hochgeladen OK')
# zweiter Tick: kein Doppel-Upload (im Log)
n_before = len(b.config.get('uploaded_results', {}))
b.watcher_tick()
assert len(b.config.get('uploaded_results', {})) == n_before, 'kein Doppel-Upload'
print('6b. Kein Doppel-Upload nach Restart-Tick OK')

# 7. TRIOS-JSON: Watcher erkennt .json, mapped auf Upload (Stem), versioniert Name
import json as _json
exp_json = Path(_tmp) / 'TRIOS' / 'Data'
# Englische TRIOS-JSON mit StartTime -> versionierter Name erwartet
en_json = {
    "Schema": {"Url": "https://software.tainstruments.com/schemas/TRIOSJSONExportSchema"},
    "Sample": {"Name": "Probe A", "PanType": "Platinum HT", "Mass": {"Value": 10.5, "Unit": {"Name": "mg"}}},
    "Procedure": {"Name": "10K to 400", "Steps": [{"Name": "Ramp"}]},
    "StartTime": "2026-09-07T10:30:00",
    "Operators": [{"Name": "OP"}],
    "Results": {"Processed": {
        "Classification": {"Id": "Latest", "Description": "x"},
        "ResultsSteps": [{"Name": "Ramp", "Id": "a"}],
        "ColumnHeaders": {
            "Time_min": {"DisplayName": "Time", "ValueType": "Number", "Unit": {"Name": "min"}},
            "Temperature_°C": {"DisplayName": "Temperature", "ValueType": "Number", "Unit": {"Name": "°C"}},
            "Weight_%": {"DisplayName": "Weight", "ValueType": "Number", "Unit": {"Name": "%"}},
            "Weight_mg": {"DisplayName": "Weight", "ValueType": "Number", "Unit": {"Name": "mg"}},
        },
        "Rows": [
            {"Time_min": 0.0, "Temperature_°C": 30.0, "Weight_%": 100.0, "Weight_mg": 10.5},
            {"Time_min": 1.0, "Temperature_°C": 400.0, "Weight_%": 30.0, "Weight_mg": 3.15},
        ]
    }}
}
# file_owner: nach save_slot_files hat 'Probe A_01.tprc' -> AAA111 (aus Test 5)
json_fname = 'Probe A_01.json'
(exp_json / json_fname).write_text(_json.dumps(en_json), encoding='utf-8')
# Watcher: .json ist NEU (vorher nur .tri/.xlsx gesehen)
b.watcher_tick()   # Runde nach dem .tri aus Test 6 — .json ist jetzt neu
# Mapping: 'Probe A_01.json' -> stem 'Probe A_01' -> file_owner['Probe A_01.tprc'] = AAA111
uid_mapped = b._map_result_to_upload(json_fname, exp_json)
assert uid_mapped == 'AAA111', f"JSON-Mapping: erwartet AAA111, habe {uid_mapped}"
# Versionierter Name enthält StartTime
vname = b._json_versioned_name(json_fname, exp_json)
assert '2026-09-07' in vname.replace('_', ' ') or '2026_09_07' in vname, f"Versionierung fehlt: {vname}"
print(f'7. TRIOS-JSON erkannt + Mapping AAA111 + versioniert ({vname}) OK')

# 8. JSON-Mapping via Sample-Name (Fallback ohne Stem-Treffer) + upload_raw Aufruf
class CountingClient(FakeClient):
    def __init__(self):
        super().__init__()
        self.uploaded = []
        self.published = []
    def upload_raw(self, uid, rel, filepath):
        self.uploaded.append((uid, rel))
        return True
    def publish(self, uid, embargo_length=36):
        self.published.append((uid, embargo_length))
        return True
cc = CountingClient()
b2 = Backend(client=cc)
b2.file_owner = dict(b.file_owner)  # 'Probe A_01.tprc' -> AAA111 (aus Test 5)
# uploads: nur die Zeile mit sample 'Probe A' (AAA111) — für Sample-Name-Mapping
b2.uploads = [r for r in b.uploads if r['upload_id'] == 'AAA111']
# 'Probe C_99.json' hat KEINEN Stem-Treffer (kein 'Probe C_99.tprc' owner),
# aber JSON Sample.Name = 'Probe A' -> matcht Upload AAA111 (sample 'Probe A')
json_c = 'Probe C_99.json'
(exp_json / json_c).write_text(_json.dumps(en_json), encoding='utf-8')
uid2 = b2._map_result_to_upload(json_c, exp_json)
assert uid2 == 'AAA111', f"Sample-Name-Mapping: erwartet AAA111, habe {uid2}"
# upload_result mit versioniertem Namen -> CountingClient.uploaded
b2.upload_result(uid2, str(exp_json / json_c),
                 versioned_name=b2._json_versioned_name(json_c, exp_json))
assert cc.uploaded and cc.uploaded[0][0] == 'AAA111', f"Upload fehlt: {cc.uploaded}"
print(f'8. JSON Sample-Name-Mapping + Upload OK: {cc.uploaded}')

print('\nALLE BACKEND-TESTS BESTANDEN')

# ── Zusatztests für EXE-Issue-Fixes ────────────────────────────

# Issue #1: Eine NOMAD-Entry-Mainfile '*.archive.json' ist KEIN Messergebnis.
# Vor dem Fix zählte sie als has_json → Uploads mit nur .tprc + archive.json
# standen sofort auf 'measured', obwohl nie gemessen wurde.
class ArchiveJsonClient(FakeClient):
    def list_raw_files(self, uid):
        # AAA111-artiger Upload: .tprc + NOMAD-Mainfile (.archive.json)
        if uid == 'AAA111':
            return [{'name': 'Sample.tprc', 'size': 2550, 'is_file': True},
                    {'name': 'AAA111.archive.json', 'size': 500, 'is_file': True}]
        return []

b3 = Backend(client=ArchiveJsonClient())
b3.config['sample_status'] = {}    # frühere Tests setzten AAA111 auf received
b3.config['slot_assignments'] = {}  # ...und auf Slot 01 (→ assigned statt pending)
rows3 = b3.refresh()
a3 = next(r for r in rows3 if r['upload_id'] == 'AAA111')
assert not a3['has_json'], f'archive.json darf nicht als Ergebnis zählen: {a3["has_json"]}'
assert not a3['has_result'], f'has_result muss False sein: {a3["has_result"]}'
assert b3.display_status('AAA111', a3['has_result']) == 'pending', \
    'Upload mit nur .tprc+archive.json muss pending sein, nicht measured'
print('FIX #1: .archive.json zählt nicht als Ergebnis → kein Sofort-measured OK')

# Issue #4: download_tprc soll bei vergebenem Slot {Sample}_{Slot}.tprc
# speichern (nicht den rohen Upload-Namen).
imp4 = Path(_tmp) / 'TRIOS' / 'Methods4'
imp4.mkdir(parents=True, exist_ok=True)
b4 = Backend(client=FakeClient())
b4.refresh()
b4.assign_slot('AAA111', '07')
saved4 = b4.download_tprc('AAA111', import_dir=imp4)
assert saved4 and Path(saved4[0]).name == 'Probe A_07.tprc', \
    f'Slot muss in den Dateinamen: {saved4}'
assert b4.file_owner.get('Probe A_07.tprc') == 'AAA111'
print(f'FIX #4: download_tprc mit Slot → {Path(saved4[0]).name} OK')
# ohne Slot bleibt der Originalname (BBB222 hat .tprc, aber keinen Slot)
imp4b = Path(_tmp) / 'TRIOS' / 'Methods4b'
imp4b.mkdir(parents=True, exist_ok=True)
saved4b = b4.download_tprc('BBB222', import_dir=imp4b)
assert saved4b and Path(saved4b[0]).name == 'Sample.tprc', f'ohne Slot Originalname: {saved4b}'
print('FIX #4b: download_tprc ohne Slot → Originalname OK')

# Issue #3: has_result (nicht has_tri) entscheidet über measured — auch wenn
# nur eine TRIOS-JSON (.json) als Ergebnis da ist, kein .tri.
class JsonResultClient(FakeClient):
    def list_raw_files(self, uid):
        if uid == 'AAA111':
            return [{'name': 'Sample.tprc', 'size': 2550, 'is_file': True},
                    {'name': 'Probe A_01.json', 'size': 200, 'is_file': True}]
        return []

b5 = Backend(client=JsonResultClient())
b5.config['sample_status'] = {}    # Altlasten aus früheren Tests entfernen
b5.config['slot_assignments'] = {}
rows5 = b5.refresh()
a5 = next(r for r in rows5 if r['upload_id'] == 'AAA111')
assert a5['has_json'] and a5['has_result'] and not a5['has_tri']
assert b5.display_status('AAA111', a5['has_result']) == 'measured'
print('FIX #3: has_result erkennt reine JSON-Ergebnisse → measured OK')

# E2E-Race: upload_result muss processing asynchron triggern (nicht im
# UI-Thread blockieren) und NUR wenn der Upload idle ist.
import time as _time
class BusyClient(FakeClient):
    def __init__(self):
        super().__init__()
        self.busy_calls = 0
    def wait_until_idle(self, uid, timeout=180, poll=3):
        self.busy_calls += 1
        return True  # sofort idle (Fake)

b6 = Backend(client=BusyClient())
b6.config['sample_status'] = {}
b6.config['slot_assignments'] = {}
b6.refresh()
res6 = Path(_tmp) / 'TRIOS' / 'Data6'
res6.mkdir(parents=True, exist_ok=True)
f6 = res6 / 'Probe A.json'
f6.write_text('{"Sample": {"Name": "Probe A"}}', encoding='utf-8')
b6.upload_result('AAA111', str(f6))
_time.sleep(6.5)  # Daemon-Thread: 5s PUT-Registrierungs-Puffer + Trigger
assert getattr(b6.client, 'triggers', []) == ['AAA111'], \
    f'upload_result muss trigger_process auslösen: {getattr(b6.client, "triggers", [])}'
assert b6.client.busy_calls >= 1, 'wait_until_idle muss vor dem Trigger laufen'
print('E2E-RACE: upload_result → wait_until_idle + async trigger_process OK')

print('\nALLE ISSUE-FIX-TESTS BESTANDEN')
