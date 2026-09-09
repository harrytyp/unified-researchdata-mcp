"""Backend logic for the TGA operator app — pure Python, no UI imports.

Contains: config, sample status, entry metadata helpers, slot assignment
(filename stage), and the TRIOS export folder watcher.
All state lives in a single Backend instance owned by the UI.
"""
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from nomad_client import NomadApiError

# ─── Config ────────────────────────────────────────────────────

CONFIG_FILE = Path.home() / '.tga_nomad_config.json'
DEFAULT_CONFIG = {
    'nomad_url': 'https://researchmcp.duckdns.org/nomad-oasis',
    'nomad_pat': '',
    'trios_import_dir': str(Path.home() / 'TRIOS' / 'Methods'),
    'trios_export_dir': str(Path.home() / 'TRIOS' / 'Data'),
    'auto_download': True,
    'auto_upload': True,
    'poll_interval': 15,
    'verify_ssl': False,
    'sample_status': {},           # upload_id -> {'status': ..., 'ts': iso}
    'auto_mark_measured': True,
    'slot_assignments': {},        # upload_id -> {'slot': '03', 'ts': iso}
    'dark_mode': False,
    'language': 'en',              # 'en' (default) or 'de'
    'debug_mode': False,           # True = demo data (FakeClient), no PAT needed
    'uploaded_results': {},        # export-filename -> {'target': '<uploaded-versioned-name>', 'ts': iso}
                                  # PERSISTENT log of what the watcher already uploaded — so a
                                  # restart (EXE started AFTER TRIOS finished) does NOT re-upload
                                  # files that are already in NOMAD, but DOES pick up files that
                                  # were present before the app started and never uploaded.
}

STATUSES = ('pending', 'received', 'assigned', 'measured')

STATUS_LABELS = {
    'pending': '○ Angekommen',
    'received': '● Im Labor',
    'assigned': '◫ Im Pan',
    'measured': '◉ Gemessen',
}

STATUS_LABELS_EN = {
    'pending': '○ Arrived',
    'received': '● In lab',
    'assigned': '◫ In pan',
    'measured': '◉ Measured',
}


def i18n(cfg, status_key: str) -> str:
    """Status label in the configured language."""
    if cfg.get('language') == 'de':
        return STATUS_LABELS[status_key]
    return STATUS_LABELS_EN[status_key]


def load_config():
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                cfg = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                cfg.setdefault(k, v)
            return cfg
        except Exception:
            return dict(DEFAULT_CONFIG)
    return dict(DEFAULT_CONFIG)


def save_config(cfg):
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        raise RuntimeError(f'Could not save config: {e}')


# ─── Entry metadata helpers ────────────────────────────────────

def procedure_label(ed):
    """procedure_name, else derived description from segments, else empty."""
    name = ed.get('procedure_name')
    if name:
        return str(name)[:60]
    segs = ed.get('temperature_segments') or []
    if segs:
        kinds = ', '.join(str(s.get('segment_type', '?')) for s in segs if isinstance(s, dict))
        return f'{len(segs)} Seg: {kinds}'
    return ''


def author_name(md, upload, cache):
    """Resolve user_id -> real name from entry_metadata.main_author.name.

    Verified: GET /uploads/{id}/entries returns main_author as an object
    {'user_id': ..., 'name': 'Kolja Knodel'} — no extra API call needed.
    """
    ma = md.get('main_author') or {}
    if isinstance(ma, dict):
        name, user_id = str(ma.get('name') or ''), str(ma.get('user_id') or '')
    else:
        name, user_id = '', str(ma or upload.get('main_author') or '')
    if not name:
        for a in (md.get('authors') or []):
            if isinstance(a, dict) and a.get('name'):
                name, user_id = str(a['name']), str(a.get('user_id') or user_id)
                break
    if not name:
        name = cache.get(user_id, '')
    if not name:
        name = f'unknown ({user_id[:8]}…)' if user_id else 'unknown'
    else:
        cache[user_id] = name
    return name


# ─── Slot helpers ──────────────────────────────────────────────

def slot_guid_for(label):
    """Stable GUID from a slot label — documented placeholder convention."""
    import uuid
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f'tga-slot:{label.strip()}')).upper()


def patch_tprc_slot_guid(data, slot_label):
    """Replace the NULL slot GUID in place (search-based, 36 chars).

    NOT enabled by default — see docs/autosampler-slots.md. Kept here so the
    next stage can flip it on once the TRIOS pan GUID convention is verified.
    """
    null_guid = b'00000000-0000-0000-0000-000000000000'
    raw = bytearray(data)
    idx = raw.find(null_guid)
    if idx < 0:
        raise ValueError('No NULL slot GUID found (slot already assigned?)')
    if idx == 0 or raw[idx - 1] != 0x24:
        raise ValueError(f'Unexpected length prefix {raw[idx - 1]:#04x} before slot GUID')
    guid = slot_guid_for(slot_label)
    raw[idx:idx + 36] = guid.encode('ascii')
    return bytes(raw)


def slot_filename(sample, slot, uid):
    """Filename convention: {Sample}_{Slot}.tprc (unique .tri names via stem)."""
    base = sample if sample else f'exp{uid[:8]}'
    return f'{base}_{slot}.tprc'


# ─── Backend ───────────────────────────────────────────────────

class Backend:
    """All app state + business logic. UI-agnostic; UI calls these methods."""

    def __init__(self, client=None):
        self.refreshing = False
        self.config = load_config()
        self.client = client
        self.uploads = []            # enriched upload dicts (UI rows/cards)
        self.author_cache = {}       # user_id -> name
        self.file_owner = {}         # local filename -> upload_id
        self.log_lines = []          # [(ts, tag, msg)] for the UI log
        self.watcher_running = False
        self.last_scan = None
        self.on_log = None           # callback(ts, tag, msg) — set by UI

    # ── Logging ────────────────────────────────────────────────

    def log(self, msg, tag='info'):
        entry = (datetime.now().strftime('%H:%M:%S'), tag, msg)
        self.log_lines.append(entry)
        if len(self.log_lines) > 500:
            self.log_lines = self.log_lines[-500:]
        if self.on_log:
            self.on_log(*entry)

    # ── Status ─────────────────────────────────────────────────

    def manual_status(self, uid):
        st = (self.config.get('sample_status') or {}).get(uid)
        if isinstance(st, dict):
            return st.get('status') if st.get('status') in STATUSES else None
        return st if st in STATUSES else None

    def display_status(self, uid, has_result=False):
        manual = self.manual_status(uid)
        if manual:
            return manual
        if has_result and self.config.get('auto_mark_measured', True):
            return 'measured'
        slot = self.slot_for(uid)
        if slot:
            return 'assigned'
        return 'pending'

    def set_status(self, uid, status):
        if not uid or status not in STATUSES:
            return
        self.config.setdefault('sample_status', {})[uid] = {
            'status': status, 'ts': datetime.now().isoformat(timespec='seconds')}
        # Leaving 'assigned' (to ANY other status, incl. measured) means the
        # sample left the pan: clear its slot so it disappears from the grid.
        if status != 'assigned' and uid in self.config.get('slot_assignments', {}):
            del self.config['slot_assignments'][uid]
        try:
            save_config(self.config)
        except Exception as e:
            self.log(f'Could not save status: {e}', 'err')
        self.log(f'Status {uid[:8]} → {status}', 'ok')

    def clear_status(self, uid):
        if uid in self.config.get('sample_status', {}):
            del self.config['sample_status'][uid]
            try:
                save_config(self.config)
            except Exception as e:
                self.log(f'Could not save status: {e}', 'err')

    def slot_for(self, uid):
        a = (self.config.get('slot_assignments') or {}).get(uid)
        return a.get('slot') if isinstance(a, dict) else None

    def assign_slot(self, uid, slot):
        self.config.setdefault('slot_assignments', {})[uid] = {
            'slot': slot, 'ts': datetime.now().isoformat(timespec='seconds')}
        # Placing a sample in the pan means it is 'assigned' — this overrides
        # any manual 'received'/'pending' status.
        self.config.setdefault('sample_status', {})[uid] = {
            'status': 'assigned', 'ts': datetime.now().isoformat(timespec='seconds')}
        try:
            save_config(self.config)
        except Exception as e:
            self.log(f'Could not save slot: {e}', 'err')
        self.log(f'Slot {slot} → {uid[:8]}', 'ok')

    def clear_slot(self, uid):
        if uid in self.config.get('slot_assignments', {}):
            del self.config['slot_assignments'][uid]
            try:
                save_config(self.config)
            except Exception as e:
                self.log(f'Could not clear slot: {e}', 'err')

    # ── Data loading ────────────────────────────────────────────

    def _enrich_upload(self, up):
        uid = up.get('upload_id', up.get('id', ''))
        if not uid:
            return None
        name = up.get('upload_name') or f'Upload {uid[:8]}'
        created = (up.get('upload_create_time', '') or '')[:16]
        entries = []
        try:
            entries = self.client.list_upload_entries(uid) or []
        except NomadApiError as e:
            self.log(f'  entries {uid[:8]}: {e}', 'warn')
        tga = []
        entry_ids = []
        entry_names = []
        for e in entries:
            md = e.get('entry_metadata') or {} if isinstance(e, dict) else {}
            if 'TgaMeasurement' in str(md.get('entry_type', '')):
                tga.append(md)
                eid = e.get('entry_id') if isinstance(e, dict) else None
                if eid:
                    entry_ids.append(str(eid))
                ename = e.get('entry_name') if isinstance(e, dict) else None
                if ename:
                    entry_names.append(str(ename))
        if not tga:
            return None
        files = []
        try:
            files = self.client.list_raw_files(uid) or []
        except NomadApiError as e:
            self.log(f'  rawdir {uid[:8]}: {e}', 'warn')
        fnames = []
        for f in files:
            if isinstance(f, dict):
                fnames.append(f.get('path', f.get('name', '')))
            else:
                fnames.append(str(f))
        has_tprc = any(str(f).lower().endswith('.tprc') for f in fnames)
        has_tri = any(str(f).lower().endswith(('.tri', '.xlsx')) for f in fnames)
        # NOMAD stores each entry's mainfile as '*.archive.json' in the upload
        # — that is NOT a TRIOS result. Counting it made every fresh upload
        # (entry + generated .tprc) show 'measured' immediately, before any
        # measurement existed (same .archive.json bug as the server plugin).
        has_json = any(str(f).lower().endswith('.json')
                       and not str(f).lower().endswith('.archive.json')
                       for f in fnames)
        md0 = tga[0] if tga else {}
        ed = md0.get('data') or {}
        # Display name: prefer the ELN sample_name; fall back to the
        # .tprc filename stem (Sample.tprc -> Sample), the entry name,
        # or the entry id. NEVER "Upload {random-id}" as the title —
        # that made the board unusable when users left the sample
        # field empty.
        sample_name = str((ed.get('sample') or {}).get('sample_name', '')).strip()
        if not sample_name:
            # Prefer the tprc_filename the ELN wrote (may or may not
            # carry a .tprc extension), then the raw .tprc stem, then
            # the entry name stem, then the entry id.
            tprc_file = str(ed.get('tprc_filename') or '').strip()
            if tprc_file:
                sample_name = Path(tprc_file).stem
            else:
                raw_stem = next((Path(str(f)).stem for f in fnames
                                 if str(f).lower().endswith('.tprc')), '')
                entry_stem = Path(str(entry_names[0] if entry_names else '')).stem
                sample_name = (raw_stem or entry_stem
                               or str(entry_ids[0] or uid))[:60]
        row = {
            'upload_id': uid,
            'name': name,
            'sample': sample_name[:60],
            'entry_type': str(md0.get('entry_type') or 'TgaMeasurement'),
            'procedure': procedure_label(ed),
            'author': author_name(md0, up, self.author_cache),
            'segments': ed.get('temperature_segments') or [],
            'entry_id': entry_ids[0] if entry_ids else None,
            'has_tprc': has_tprc,
            'has_tri': has_tri,
            'has_json': has_json,
            'has_result': has_tri or has_json,
            'entries': len(tga),
            'created': created,
            'files': fnames,
        }
        if (has_tri or has_json) and self.manual_status(uid) is None \
                and self.config.get('auto_mark_measured', True):
            self.config.setdefault('sample_status', {})[uid] = {
                'status': 'measured',
                'ts': datetime.now().isoformat(timespec='seconds')}
        for f in fnames:
            if str(f).lower().endswith('.tprc'):
                self.file_owner[str(f)] = uid
        return row
    def refresh(self):
        """Fetch all TGA uploads and enrich them. Returns list of dicts."""
        if not self.client:
            self.log('Not connected — set NOMAD URL + PAT first', 'err')
            return []
        self.refreshing = True
        try:
            uploads = self.client.list_uploads(per_page=100)
            # Enrich uploads IN PARALLEL: each upload needs 2 HTTP calls
            # (entries + rawdir); sequential = 2*N roundtrips and the main
            # reason the app felt slow to start (~3s for 17 -> ~0.5s).
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(self._enrich_upload, uploads))
            rows = [r for r in results if r]
            self.uploads = rows
            self.refreshing = False
            self.log(f'Refresh: {len(rows)} TGA upload(s)', 'ok')
            return rows
        except NomadApiError as e:
            self.refreshing = False
            self.log(f'Refresh failed: {e}', 'err')
            return []
        except Exception as e:
            self.refreshing = False
            self.log(f'Refresh error: {e}', 'err')
            return []

    # ── Downloads / uploads ────────────────────────────────────

    def download_tprc(self, uid, import_dir=None):
        """Download all .tprc of one upload; returns list of saved paths.

        If the upload already has a slot assignment, the file is saved as
        ``{Sample}_{Slot}.tprc`` (the slot_filename convention) instead of
        the raw upload name — so TRIOS exports (named after the method file)
        keep the slot in their stem and the watcher can map them back.
        """
        import_dir = Path(import_dir or self.config.get('trios_import_dir', ''))
        import_dir.mkdir(parents=True, exist_ok=True)
        files = self.client.list_raw_files(uid) or []
        row = next((r for r in self.uploads if r['upload_id'] == uid), None)
        slot = self.slot_for(uid)
        saved = []
        for f in files:
            fname = f.get('path', f.get('name', '')) if isinstance(f, dict) else str(f)
            if str(fname).lower().endswith('.tprc'):
                dest_name = Path(fname).name
                if slot and row:
                    dest_name = slot_filename(row.get('sample', ''), slot, uid)
                dest = import_dir / dest_name
                n = self.client.download_raw(uid, fname, str(dest))
                self.file_owner[dest.name] = uid
                self.log(f'Downloaded {Path(fname).name} ({n} B)', 'ok')
                saved.append(str(dest))
        return saved

    def save_slot_files(self, assignments, import_dir=None):
        """Download each .tprc as {Sample}_{Slot}.tprc (filename stage).

        assignments: list of {'upload_id', 'sample'} — slots are assigned HERE
        (atomically with the file work), not by the caller, so a concurrent
        watcher tick cannot hand out the same slot twice.
        """
        import_dir = Path(import_dir or self.config.get('trios_import_dir', ''))
        import_dir.mkdir(parents=True, exist_ok=True)
        used = {self.slot_for(r['upload_id'])
                for r in self.uploads if self.slot_for(r['upload_id'])}
        free = [f'{n:02d}' for n in range(1, 31) if f'{n:02d}' not in used]
        ok, failed = [], []
        for a in assignments:
            try:
                uid = a['upload_id']
                files = self.client.list_raw_files(uid) or []
                rel = next((str(f.get('path', f.get('name', ''))) for f in files
                            if str(f.get('path', f.get('name', ''))).lower().endswith('.tprc')), None)
                if not rel:
                    raise RuntimeError('no .tprc in this upload')
                # Take the slot ONLY after the .tprc exists — otherwise a
                # failed sample burns a slot number (slots shift: 3-4 statt
                # 1-2 for the samples that DO have a tprc).
                if not free:
                    raise RuntimeError('no free slot left')
                slot = free.pop(0)
                new_name = slot_filename(a.get('sample', ''), slot, uid)
                tmp = import_dir / f'.tmp_{Path(rel).name}'
                self.client.download_raw(uid, rel, str(tmp))
                dest = import_dir / new_name
                dest.write_bytes(tmp.read_bytes())
                tmp.unlink(missing_ok=True)
                self.file_owner[dest.name] = uid
                self.assign_slot(uid, slot)
                self.log(f'Slot {slot}: {new_name} ready', 'ok')
                ok.append(str(dest))
            except Exception as e:
                self.log(f'Slot assignment failed ({a.get("upload_id", "?")}): {e}', 'err')
                failed.append(str(e))
        return ok, failed

    def upload_result(self, uid, filepath, versioned_name=None):
        """Upload a .tri/.xlsx/.json result into an upload + trigger processing.

        versioned_name: optional alternate filename (e.g. a TRIOS JSON gets a
        unique name so re-measurements don't overwrite earlier results).
        """
        fname = Path(filepath).name
        if versioned_name:
            fname = versioned_name
        self.client.upload_raw(uid, fname, filepath)
        self.log(f'Uploaded {fname} → {uid[:8]}', 'ok')
        if self.manual_status(uid) is None and self.config.get('auto_mark_measured', True):
            self.set_status(uid, 'measured')
        self._trigger_process_async(uid)

    def _trigger_process_async(self, uid):
        """Trigger (re-)processing in a background thread, but only once the
        upload is idle.

        NOMAD rejects a process trigger while another workflow still runs
        (the raw-file PUT itself starts one → 'Upload is currently being
        processed by another workflow'), which silently swallowed result
        processing in the watcher flow. Waiting here must NOT block the UI
        thread (watcher_tick runs on a ui.timer), hence the daemon thread.
        """
        import threading

        def _run():
            try:
                if not self.client.wait_until_idle(uid, timeout=180):
                    self.log(f'Processing wait timeout for {uid[:8]}', 'warn')
                    return
                for attempt in range(3):
                    try:
                        self.client.trigger_process(uid)
                        self.log('Processing triggered', 'ok')
                        return
                    except NomadApiError as e:
                        busy = 'currently being processed' in str(e).lower()
                        if attempt == 2 or not busy:
                            raise
                        self.log(f'Processing busy, retry {attempt + 1}/3', 'warn')
                        import time as _time
                        _time.sleep(6)
            except NomadApiError as e:
                self.log(f'Process trigger failed: {e}', 'warn')
            except Exception as e:
                self.log(f'Process trigger error: {e}', 'warn')

        threading.Thread(target=_run, daemon=True).start()

    def _map_result_to_upload(self, fname, export_dir):
        """Map a result file (.json/.tri) to an upload_id.

        Priority:
          1. exact filename -> owner (file_owner maps downloaded .tprc names)
          2. stem + '.tprc' -> owner (e.g. 'Probe A_03.json' -> 'Probe A_03.tprc')
          3. For JSON: sample name inside the file against upload samples
        Returns upload_id or None.
        """
        stem = Path(fname).stem
        uid = self.file_owner.get(fname) or self.file_owner.get(f'{stem}.tprc')
        if uid:
            return uid
        if str(fname).lower().endswith('.json'):
            # Sample-name fallback: read Sample.Name from the JSON header
            try:
                import json as _json
                with open(export_dir / fname, encoding='utf-8-sig') as f:
                    d = _json.load(f)
                sname = ((d.get('Sample') or {}).get('Name') or '').strip()
                if sname:
                    for r in self.uploads:
                        if r.get('sample') and sname.lower() in str(r['sample']).lower():
                            return r['upload_id']
            except Exception:
                pass
        return None

    def _json_versioned_name(self, fname, export_dir):
        """Version a TRIOS JSON upload name with its StartTime (if available),
        so re-measurements of the same sample don't overwrite each other.
        Falls back to the plain filename."""
        try:
            import json as _json
            with open(export_dir / fname, encoding='utf-8-sig') as f:
                d = _json.load(f)
            start = (d.get('StartTime') or '').replace(':', '').replace('T', '_')
            start = start[:15]
            if start:
                base = Path(fname).stem
                return f'{base}_{start}.json'
        except Exception:
            pass
        return fname

    def _already_uploaded(self, fname, target_name=None):
        """Check the persistent uploaded_results log (by export filename OR
        by the versioned target name it was uploaded as).

        A ':nomatch' entry means the file had no matching upload on a previous
        tick (e.g. the app had not refreshed yet) — that is NOT 'uploaded',
        so it is retried on later ticks.
        """
        log = self.config.get('uploaded_results') or {}
        entry = log.get(fname)
        if entry:
            if isinstance(entry, dict) and str(entry.get('target', '')).endswith(':nomatch'):
                return False  # retry later
            return True
        if target_name:
            for v in log.values():
                if isinstance(v, dict) and v.get('target') == target_name:
                    return True
        return False

    def _mark_uploaded(self, fname, target_name):
        """Persist that an export file was uploaded (survives restart)."""
        self.config.setdefault('uploaded_results', {})[fname] = {
            'target': target_name,
            'ts': datetime.now().isoformat(timespec='seconds'),
        }
        try:
            save_config(self.config)
        except Exception as e:
            self.log(f'Could not save upload log: {e}', 'err')

    def watcher_tick(self):
        """One watcher pass: scan export dir for .json/.tri/.xlsx results and
        upload files that have NOT been uploaded yet.

        Restart-safe: the app may be started AFTER TRIOS already exported the
        result files (operator starts the EXE when the measurement is done).
        Two guards prevent duplicate uploads:
          - ``uploaded_results`` (persistent config log) records every file
            the watcher uploaded, keyed by export filename AND by the
            versioned target name.
          - A file already present in the target upload (checked against the
            upload's raw files) is skipped even if the log was cleared.
        """
        export_dir = Path(self.config.get('trios_export_dir', ''))
        if not export_dir.exists():
            return
        current = set(f.name for f in export_dir.glob('*.tri')) | \
                  set(f.name for f in export_dir.glob('*.xlsx')) | \
                  set(f.name for f in export_dir.glob('*.json'))
        self.last_scan = datetime.now().strftime('%H:%M:%S')

        for fname in sorted(current):
            fpath = export_dir / fname
            # Skip files already uploaded (persistent log survives restart)
            if self._already_uploaded(fname):
                continue
            if not self.config.get('auto_upload', True):
                # remember we saw it so we don't warn every tick, but still
                # allow it to be picked up if auto_upload is enabled later
                continue
            uid = self._map_result_to_upload(fname, export_dir)
            if not uid:
                # Warn once per run (not every tick) — but keep retrying the
                # mapping on later ticks (the upload may appear after refresh).
                if not hasattr(self, '_nomatch_warned') or fname not in self._nomatch_warned:
                    self.log(f'  No matching upload for {fname} — use Upload manually', 'warn')
                    if not hasattr(self, '_nomatch_warned'):
                        self._nomatch_warned = set()
                    self._nomatch_warned.add(fname)
                continue
            # Version JSON names so re-measurements don't overwrite
            vname = self._json_versioned_name(fname, export_dir) \
                if str(fname).lower().endswith('.json') else fname
            # Skip if the versioned target name is already in the target upload
            try:
                existing = {f.get('path', f.get('name', ''))
                            for f in (self.client.list_raw_files(uid) or [])}
                if vname in existing:
                    self._mark_uploaded(fname, vname)
                    continue
            except Exception:
                pass
            self.log(f'New result file: {fname}', 'ok')
            try:
                self.upload_result(uid, str(fpath), versioned_name=vname if vname != fname else None)
                self._mark_uploaded(fname, vname)
            except NomadApiError as e:
                self.log(f'  Upload failed for {fname}: {e}', 'err')
        self._seen_files = current

