"""Fake NOMAD client for tests (TGA_FAKE_CLIENT=1) — no network needed."""
from pathlib import Path


class FakeClient:
    def __init__(self):
        self.tprc = b'\tVERSIONED' + b'\x00' * 120

    def check_health(self):
        return True, 'ok'

    def list_uploads(self, per_page=100):
        return [
            {'upload_id': 'AAA111', 'upload_name': None,
             'upload_create_time': '2026-08-01T10:00:00', 'entries': 1},
            {'upload_id': 'BBB222', 'upload_name': None,
             'upload_create_time': '2026-08-02T10:00:00', 'entries': 1},
            {'upload_id': 'CCC333', 'upload_name': None,
             'upload_create_time': '2026-08-03T10:00:00', 'entries': 1},
        ]

    def list_upload_entries(self, uid):
        base = {'entry_type': 'TgaMeasurement',
                'main_author': {'user_id': 'u1', 'name': 'Kolja Knodel'},
                'data': {'sample': {'sample_name': 'Probe A'},
                         'procedure_name': '10K_min',
                         'temperature_segments': [
                             {'segment_type': 'ramp', 'end_temp': 400, 'rate': 10}]}}
        if uid == 'BBB222':
            base['data']['sample']['sample_name'] = 'Probe B'
            base['data']['procedure_name'] = '5K_iso'
        if uid == 'CCC333':
            base['data']['sample']['sample_name'] = 'Probe C'
        # Real NOMAD entries carry an entry_id (verified against the server).
        return [{'entry_id': f'ENTRY-{uid}', 'entry_metadata': base}]

    def list_raw_files(self, uid):
        if uid == 'AAA111':
            return [{'name': 'Sample.tprc', 'size': 2550, 'is_file': True}]
        if uid == 'BBB222':
            return [{'name': 'Sample.tprc', 'size': 2550, 'is_file': True},
                    {'name': 'result.tri', 'size': 100, 'is_file': True}]
        return []

    def download_raw(self, uid, rel, dest):
        Path(dest).write_bytes(self.tprc)
        return len(self.tprc)

    def download_raw_bytes(self, uid, rel):
        return self.tprc

    def upload_raw(self, *a, **k):
        return True

    def trigger_process(self, uid):
        return True
