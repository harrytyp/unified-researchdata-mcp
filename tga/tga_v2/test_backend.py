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
            return [{'name': 'result.tri', 'size': 100, 'is_file': True}]
        return []
    def download_raw(self, uid, rel, dest):
        Path(dest).write_bytes(self.tprc)
        return len(self.tprc)
    def upload_raw(self, *a, **k):
        return True
    def trigger_process(self, uid):
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
assert b.display_status('BBB222', has_tri=True) == 'measured'
assert b.display_status('AAA111', has_tri=False) == 'pending'
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
assert b.display_status('AAA111', has_tri=False) == 'assigned'  # Slot -> assigned
assert slot_filename('Probe A', '03', 'AAA111') == 'Probe A_03.tprc'
print('4. Slot-Zuweisung + display_status=assigned OK')

# 5. save_slot_files (lädt .tprc als {Sample}_{Slot}.tprc)
import_dir = Path(_tmp) / 'TRIOS' / 'Methods'
ok, failed = b.save_slot_files([{'upload_id': 'AAA111', 'sample': 'Probe A', 'slot': '03'}], import_dir)
assert ok and (import_dir / 'Probe A_03.tprc').exists(), f'ok={ok} failed={failed}'
print(f'5. Slot-Dateien OK: {(import_dir / "Probe A_03.tprc").name}')

# 5b. Slot wird bei Statuswechsel auf measured gelöscht (Bug-Fix)
b.assign_slot('BBB222', '05')
assert b.slot_for('BBB222') == '05'
b.set_status('BBB222', 'measured')
assert b.slot_for('BBB222') is None, 'Slot muss bei measured gelöscht werden'
assert b.display_status('BBB222', has_tri=True) == 'measured'
print('5b. Slot-Löschung bei measured OK')

# 6. Watcher: neue .tri im Exportordner -> Upload + measured
exp = Path(_tmp) / 'TRIOS' / 'Data'
exp.mkdir(parents=True, exist_ok=True)
(exp / 'Probe A_03.tri').write_bytes(b'fake tri')
# file_owner wurde beim save_slot_files gesetzt (Probe A_03.tprc -> AAA111)
b.watcher_tick()  # erste Runde: initialisiert _seen_files
(exp / 'Probe B.tri').write_bytes(b'fake tri2')
# map: Probe B.tri -> stem Probe B -> kein tprc-Owner -> warn (kein Crash)
b.watcher_tick()
assert b.last_scan is not None
print('6. Watcher-Tick OK (kein Crash, last_scan gesetzt)')

print('\nALLE BACKEND-TESTS BESTANDEN')
