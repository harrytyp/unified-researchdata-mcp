"""tga_nomad_app.pyw — Windows TGA Pipeline Agent via NOMAD.

Workflow:
  - Lists NOMAD uploads that contain TgaMeasurement entries (with .tprc)
  - Downloads the generated .tprc -> TRIOS import folder
  - Watches the TRIOS export folder for new .tri/.xlsx result files
  - Uploads results back into the SAME NOMAD upload and triggers processing

Package as .exe:  pyinstaller --onefile --noconsole tga_nomad_app.pyw
"""
import os
import sys
import json
import time
import base64
import threading
import logging
from pathlib import Path
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, filedialog
import requests
import urllib3
urllib3.disable_warnings()

# ─── Configuration ──────────────────────────────────────────────
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
    'sample_status': {},           # upload_id -> {'status': 'pending'|'received'|'measured', 'ts': iso}
    'auto_mark_measured': True,    # .tri present -> status automatically 'measured'
}


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


# ─── NOMAD API Client ───────────────────────────────────────────

class NomadApiError(Exception):
    """Raised for HTTP-level API failures (4xx/5xx)."""

    def __init__(self, status, detail=''):
        self.status = status
        self.detail = detail
        super().__init__(f'NOMAD API error {status}: {detail or "unknown"}')


class NomadClient:
    """Minimal NOMAD Oasis REST client (PAT auth)."""

    def __init__(self, base_url, pat, verify=False, timeout=20):
        self.base_url = base_url.rstrip('/')
        self.pat = pat or ''
        self.verify = verify
        self.timeout = timeout
        self.session = requests.Session()
        self.session.verify = verify

    def _headers(self):
        if not self.pat:
            raise NomadApiError(401, 'No PAT configured')
        return {'Authorization': f'Bearer {self.pat}'}

    def _request(self, method, path, **kwargs):
        url = f'{self.base_url}/api/v1{path}'
        kwargs.setdefault('headers', self._headers())
        kwargs.setdefault('timeout', self.timeout)
        try:
            resp = self.session.request(method, url, **kwargs)
        except requests.exceptions.Timeout:
            raise NomadApiError(0, f'Timeout after {self.timeout}s: {path}')
        except requests.exceptions.ConnectionError as e:
            raise NomadApiError(0, f'Connection failed: {e}')
        except requests.exceptions.RequestException as e:
            raise NomadApiError(0, f'Request failed: {e}')
        if resp.status_code >= 400:
            detail = ''
            try:
                detail = resp.json().get('detail', '') or ''
            except Exception:
                detail = resp.text[:200]
            raise NomadApiError(resp.status_code, detail)
        return resp

    def list_uploads(self, per_page=100, published=None):
        """All uploads the PAT can see (admin sees everything)."""
        params = {'per_page': per_page}
        if published is not None:
            params['published'] = 'true' if published else 'false'
        resp = self._request('GET', '/uploads', params=params)
        data = resp.json()
        return data.get('data', data) if isinstance(data, dict) else data

    def get_upload(self, upload_id):
        resp = self._request('GET', f'/uploads/{upload_id}')
        data = resp.json()
        return data.get('data', data) if isinstance(data, dict) else data

    def list_raw_files(self, upload_id):
        """List raw files of an upload as flat [{'name','size','is_file'}]."""
        try:
            resp = self._request('GET', f'/uploads/{upload_id}/rawdir/')
            data = resp.json()
        except NomadApiError as e:
            if e.status == 404:
                return []
            raise
        if isinstance(data, dict):
            meta = data.get('directory_metadata') or {}
            content = meta.get('content') or []
            out = []
            for item in content:
                if isinstance(item, dict):
                    out.append({'name': item.get('name', ''),
                                'path': item.get('name', ''),
                                'size': item.get('size', 0),
                                'is_file': item.get('is_file', True)})
                else:
                    out.append({'name': str(item), 'path': str(item),
                                'size': 0, 'is_file': True})
            return out
        return data if isinstance(data, list) else []

    def download_raw(self, upload_id, rel_path, dest_path):
        """Download a raw file to dest_path; returns bytes count."""
        resp = self._request('GET', f'/uploads/{upload_id}/raw/{rel_path}')
        Path(dest_path).write_bytes(resp.content)
        return len(resp.content)

    def upload_raw(self, upload_id, rel_path, filepath):
        """PUT a local file into the upload's raw directory.

        NOMAD 1.4.2: the URL path is the target directory and the filename
        is passed as the ``file_name`` query parameter (streaming method 2).
        """
        name = Path(filepath).name
        target_dir = str(Path(rel_path).parent) if Path(rel_path).parent != Path('.') else ''
        url_path = f'/uploads/{upload_id}/raw/{target_dir}'
        if target_dir:
            url_path = url_path.rstrip('/') + '/'
        with open(filepath, 'rb') as f:
            resp = self._request(
                'PUT', url_path,
                params={'file_name': name},
                data=f, headers={**self._headers(), 'Content-Type': 'application/octet-stream'},
            )
        return resp.status_code in (200, 201, 204)

    def trigger_process(self, upload_id):
        """Trigger (re-)processing of the upload (parses the new .tri)."""
        resp = self._request('POST', f'/uploads/{upload_id}/action/process', json={})
        return resp.status_code in (200, 201, 202)

    def list_upload_entries(self, upload_id):
        resp = self._request('GET', f'/uploads/{upload_id}/entries')
        data = resp.json()
        return data.get('data', data) if isinstance(data, dict) else data

    def check_health(self):
        """Verify PAT + connectivity; returns (ok, message)."""
        try:
            self._request('GET', '/info')
            return True, 'Connected to NOMAD'
        except NomadApiError as e:
            return False, str(e)

# ─── UI Theme ───────────────────────────────────────────────────

ACCENT = '#2563eb'
ACCENT_HOVER = '#1d4ed8'
BG = '#f8fafc'
SURFACE = '#ffffff'
INK = '#0f172a'
MUTED = '#64748b'
BORDER = '#e2e8f0'
OK = '#16a34a'
WARN = '#d97706'
ERR = '#dc2626'


def apply_theme(root):
    style = ttk.Style(root)
    try:
        style.theme_use('clam')
    except Exception:
        pass
    style.configure('.', font=('Segoe UI', 10), background=BG, foreground=INK)
    style.configure('TNotebook', background=BG, borderwidth=0)
    style.configure('TNotebook.Tab', padding=(12, 6), font=('Segoe UI', 10))
    style.map('TNotebook.Tab', background=[('selected', SURFACE)])
    style.configure('TFrame', background=BG)
    style.configure('Card.TFrame', background=SURFACE, relief='flat')
    style.configure('TLabel', background=BG, foreground=INK)
    style.configure('Card.TLabel', background=SURFACE, foreground=INK)
    style.configure('Muted.TLabel', background=SURFACE, foreground=MUTED)
    style.configure('TButton', padding=(10, 6), relief='flat', background=SURFACE, foreground=INK)
    style.map('TButton',
              background=[('active', '#e2e8f0'), ('pressed', '#cbd5e1')])
    style.configure('Accent.TButton', padding=(12, 7), background=ACCENT, foreground='#ffffff', font=('Segoe UI', 10, 'bold'))
    style.map('Accent.TButton',
              background=[('active', ACCENT_HOVER), ('disabled', '#93c5fd')])
    style.configure('Treeview', background=SURFACE, fieldbackground=SURFACE, rowheight=26, borderwidth=0)
    style.configure('Treeview.Heading', font=('Segoe UI', 10, 'bold'), background='#eef2f7', foreground=INK)
    style.map('Treeview', background=[('selected', '#dbeafe')], foreground=[('selected', INK)])
    style.configure('TEntry', fieldbackground=SURFACE, bordercolor=BORDER, padding=4)
    style.configure('Horizontal.TProgressbar', troughcolor='#e2e8f0', background=ACCENT)


# ─── Sample status model ────────────────────────────────────────

STATUS_META = {
    'pending':  {'label': '○ pending',  'tag': 'st_pending',  'fg': MUTED, 'bg': SURFACE},
    'received': {'label': '● received', 'tag': 'st_received', 'fg': OK,    'bg': '#f0fdf4'},
    'measured': {'label': '◉ measured', 'tag': 'st_measured', 'fg': '#2563eb', 'bg': '#eff6ff'},
}


# ─── Main Application ───────────────────────────────────────────

class TgaNomadApp:
    def __init__(self):
        self.config = load_config()
        self.client = None
        self.watcher_active = False
        self._seen_files = None
        self._upload_cache = {}   # upload_id -> upload dict
        self._file_owner = {}     # local filename -> upload_id (mapping for .tri)
        self._build_ui()
        self._connect()

    # ── Thread-safe UI helpers ──────────────────────────────────

    def _ui(self, fn, *args):
        """Run fn on the Tk main thread."""
        try:
            self.root.after(0, lambda: fn(*args))
        except Exception:
            pass

    def _log(self, msg, tag='info'):
        def _do():
            ts = datetime.now().strftime('%H:%M:%S')
            color = {'info': INK, 'ok': OK, 'warn': WARN, 'err': ERR}.get(tag, INK)
            self.log_area.insert(tk.END, f'[{ts}] {msg}\n', (tag,))
            self.log_area.tag_config(tag, foreground=color)
            self.log_area.see(tk.END)
        self._ui(_do)

    def _set_status(self, text, ok=None):
        def _do():
            self.status_var.set(text)
            color = INK if ok is None else (OK if ok else ERR)
            self.status_label.config(foreground=color)
        self._ui(_do)

    def _busy(self, busy):
        def _do():
            state = 'disabled' if busy else 'normal'
            for b in (self.refresh_btn, self.download_btn, self.upload_btn):
                try:
                    b.config(state=state)
                except Exception:
                    pass
        self._ui(_do)

    # ── Connection ──────────────────────────────────────────────

    def _connect(self):
        url = self.config.get('nomad_url', '')
        pat = self.config.get('nomad_pat', '')
        if not url or not pat:
            self._set_status('Not configured — add NOMAD URL + PAT', ok=False)
            return
        self.client = NomadClient(url, pat, verify=self.config.get('verify_ssl', False))
        self._set_status('Connecting…')
        threading.Thread(target=self._connect_worker, daemon=True).start()

    def _connect_worker(self):
        ok, msg = self.client.check_health()
        if ok:
            self._log('Connected to NOMAD', 'ok')
            self._set_status('Connected', ok=True)
            if self.config.get('auto_download'):
                self._start_watcher()
        else:
            self._log(f'Connection failed: {msg}', 'err')
            self._set_status('Connection failed', ok=False)

    # ── UI Construction ─────────────────────────────────────────

    def _build_ui(self):
        self.root = tk.Tk()
        self.root.title('TGA NOMAD Agent')
        self.root.geometry('860x620')
        self.root.minsize(720, 520)
        self.root.configure(bg=BG)
        self.root.protocol('WM_DELETE_WINDOW', self._on_close)
        apply_theme(self.root)

        # Header bar
        header = ttk.Frame(self.root, padding=(12, 10))
        header.pack(fill='x')
        ttk.Label(header, text='TGA Pipeline', font=('Segoe UI', 14, 'bold'),
                  background=BG, foreground=INK).pack(side='left')
        self.status_var = tk.StringVar(value='Not connected')
        self.status_label = ttk.Label(header, textvariable=self.status_var,
                                      font=('Segoe UI', 10), background=BG, foreground=MUTED)
        self.status_label.pack(side='right')

        nb = ttk.Notebook(self.root)
        nb.pack(fill='both', expand=True, padx=10, pady=(0, 8))

        self.tab_ctrl = ttk.Frame(nb)
        nb.add(self.tab_ctrl, text='Experiments')
        self._build_control_tab()

        self.tab_config = ttk.Frame(nb)
        nb.add(self.tab_config, text='Configuration')
        self._build_config_tab()

        self.tab_log = ttk.Frame(nb)
        nb.add(self.tab_log, text='Log')
        self._build_log_tab()

    def _build_control_tab(self):
        frame = ttk.Frame(self.tab_ctrl, padding=10)
        frame.pack(fill='both', expand=True)

        # Actions row
        bf = ttk.Frame(frame)
        bf.pack(fill='x', pady=(0, 8))
        self.refresh_btn = ttk.Button(bf, text='⟳ Refresh', style='Accent.TButton',
                                      command=self._refresh_uploads)
        self.refresh_btn.pack(side='left', padx=(0, 6))
        self.download_btn = ttk.Button(bf, text='⬇ Download .tprc',
                                       command=self._download_tprc)
        self.download_btn.pack(side='left', padx=6)
        self.upload_btn = ttk.Button(bf, text='⬆ Upload .tri',
                                     command=self._upload_tri)
        self.upload_btn.pack(side='left', padx=6)
        ttk.Button(bf, text='Open Export Folder', command=self._open_folder).pack(side='left', padx=6)

        self.watch_btn = ttk.Button(bf, text='▶ Start Watcher', command=self._toggle_watcher)
        self.watch_btn.pack(side='right')

        # Uploads table
        lf = ttk.LabelFrame(frame, text='NOMAD Uploads (TgaMeasurement)', padding=6)
        lf.pack(fill='both', expand=True)
        cols = ('status', 'name', 'sample', 'tprc', 'tri', 'entries', 'created')
        self.upload_tree = ttk.Treeview(lf, columns=cols, show='headings', height=12)
        widths = {'status': 95, 'name': 205, 'sample': 145, 'tprc': 60,
                  'tri': 60, 'entries': 60, 'created': 95}
        for c in cols:
            self.upload_tree.heading(c, text='Status' if c == 'status' else c.capitalize())
            self.upload_tree.column(c, width=widths[c],
                                    anchor='w' if c in ('status', 'name', 'sample') else 'center')
        vsb = ttk.Scrollbar(lf, orient='vertical', command=self.upload_tree.yview)
        self.upload_tree.configure(yscrollcommand=vsb.set)
        self.upload_tree.pack(side='left', fill='both', expand=True)
        vsb.pack(side='right', fill='y')

        # Status interactions: double-click to toggle, right-click menu
        self.upload_tree.bind('<Double-1>', self._on_status_click)
        self.upload_tree.bind('<Button-3>', self._on_context_menu)
        self.status_menu = tk.Menu(self.root, tearoff=0)
        self.status_menu.add_command(label='● Mark as received',
                                     command=lambda: self._set_status_for(self._selected_upload_id(), 'received'))
        self.status_menu.add_command(label='○ Mark as pending',
                                     command=lambda: self._set_status_for(self._selected_upload_id(), 'pending'))
        self.status_menu.add_separator()
        self.status_menu.add_command(label='⟲ Reset to auto status',
                                     command=lambda: self._clear_status(self._selected_upload_id()))

        # Legend + watcher status
        foot = ttk.Frame(frame, padding=(0, 6))
        foot.pack(fill='x')
        ttk.Label(foot, text='●', foreground=OK, background=BG).pack(side='left')
        ttk.Label(foot, text='received   ', background=BG, foreground=MUTED).pack(side='left')
        ttk.Label(foot, text='◉', foreground='#2563eb', background=BG).pack(side='left')
        ttk.Label(foot, text='measured   ', background=BG, foreground=MUTED).pack(side='left')
        ttk.Label(foot, text='✓', foreground=OK, background=BG).pack(side='left')
        ttk.Label(foot, text='.tprc ready   ', background=BG, foreground=MUTED).pack(side='left')
        ttk.Label(foot, text='✓', foreground=WARN, background=BG).pack(side='left')
        ttk.Label(foot, text='.tri uploaded   ', background=BG, foreground=MUTED).pack(side='left')
        self.watch_status = tk.StringVar(value='Watcher: stopped')
        ttk.Label(foot, textvariable=self.watch_status, background=BG,
                  foreground=MUTED).pack(side='right')

    def _build_config_tab(self):
        frame = ttk.Frame(self.tab_config, padding=14)
        frame.pack(fill='both', expand=True)
        fields = [
            ('NOMAD URL:', 'nomad_url', False),
            ('NOMAD PAT:', 'nomad_pat', True),
            ('TRIOS Import Folder (.tprc):', 'trios_import_dir', False),
            ('TRIOS Export Folder (.tri):', 'trios_export_dir', False),
            ('Poll interval (s):', 'poll_interval', False),
        ]
        self.config_vars = {}
        for i, (label, key, secret) in enumerate(fields):
            ttk.Label(frame, text=label, background=BG).grid(row=i, column=0, sticky='w', pady=5)
            var = tk.StringVar(value=str(self.config.get(key, '')))
            show = '*' if secret else ''
            ent = ttk.Entry(frame, textvariable=var, width=56, show=show)
            ent.grid(row=i, column=1, sticky='w', padx=8, pady=5)
            if 'Folder' in label:
                ttk.Button(frame, text='Browse…',
                           command=lambda k=key, v=var: self._browse(k, v)).grid(row=i, column=2, padx=4)
            self.config_vars[key] = var

        auto = ttk.Frame(frame)
        auto.grid(row=len(fields), column=0, columnspan=3, sticky='w', pady=10)
        self.auto_dl_var = tk.BooleanVar(value=self.config.get('auto_download', True))
        self.auto_up_var = tk.BooleanVar(value=self.config.get('auto_upload', True))
        ttk.Checkbutton(auto, text='Auto-download new .tprc', variable=self.auto_dl_var).pack(side='left', padx=(0, 14))
        ttk.Checkbutton(auto, text='Auto-upload new .tri', variable=self.auto_up_var).pack(side='left')

        ttk.Button(frame, text='Save & Reconnect', style='Accent.TButton',
                   command=self._save_config).grid(row=len(fields) + 1, column=0, columnspan=2, sticky='w', pady=8)

    def _build_log_tab(self):
        frame = ttk.Frame(self.tab_log, padding=8)
        frame.pack(fill='both', expand=True)
        self.log_area = scrolledtext.ScrolledText(frame, wrap='word', height=16,
                                                  font=('Consolas', 9), bg='#0f172a', fg='#e2e8f0')
        self.log_area.pack(fill='both', expand=True)
        for tag, color in (('info', '#e2e8f0'), ('ok', '#4ade80'),
                           ('warn', '#fbbf24'), ('err', '#f87171')):
            self.log_area.tag_config(tag, foreground=color)

    # ── Sample status helpers ──────────────────────────────────

    def _manual_status(self, uid):
        """Manually set status or None."""
        st = (self.config.get('sample_status') or {}).get(uid)
        if isinstance(st, dict):
            return st.get('status') if st.get('status') in STATUS_META else None
        return st if st in STATUS_META else None

    def _display_status(self, uid, has_tri=False):
        """Effective status: manual wins, otherwise auto-derive."""
        manual = self._manual_status(uid)
        if manual:
            return manual
        return 'measured' if (has_tri and self.config.get('auto_mark_measured', True)) else 'pending'

    def _set_status_for(self, uid, status):
        """Set status + persist immediately."""
        if not uid:
            return
        statuses = self.config.setdefault('sample_status', {})
        statuses[uid] = {'status': status, 'ts': datetime.now().isoformat(timespec='seconds')}
        try:
            save_config(self.config)
        except Exception as e:
            self._log(f'Could not save status: {e}', 'err')
        self._update_row_status(uid)

    def _clear_status(self, uid):
        """Remove manual status (back to auto)."""
        if uid and uid in self.config.get('sample_status', {}):
            del self.config['sample_status'][uid]
            try:
                save_config(self.config)
            except Exception as e:
                self._log(f'Could not save status: {e}', 'err')
            self._update_row_status(uid)

    def _update_row_status(self, uid):
        """Re-render a single row without a full refresh."""
        if not self.upload_tree.exists(uid):
            return
        r = getattr(self, '_last_rows', {}).get(uid)
        if not r:
            return
        meta = STATUS_META[self._display_status(uid, r['has_tri'])]
        self.upload_tree.item(uid, tags=(meta['tag'],),
                              values=(meta['label'], r['name'], r['sample'],
                                      '✓' if r['has_tprc'] else '—',
                                      '✓' if r['has_tri'] else '—',
                                      r['entries'], r['created']))

    def _on_status_click(self, event):
        """Double-click on the Status cell toggles pending <-> received."""
        if self.upload_tree.identify('region', event.x, event.y) != 'cell':
            return
        if self.upload_tree.identify_column(event.x) != '#1':
            return
        uid = self.upload_tree.identify_row(event.y)
        if not uid:
            return
        cur = self._manual_status(uid) or 'pending'
        self._set_status_for(uid, 'received' if cur != 'received' else 'pending')

    def _on_context_menu(self, event):
        row = self.upload_tree.identify_row(event.y)
        if row:
            self.upload_tree.selection_set(row)
            self.status_menu.tk_popup(event.x_root, event.y_root)

    # ── Data: Refresh uploads ───────────────────────────────────

    def _refresh_uploads(self):
        if not self.client:
            self._log('Not connected — set NOMAD URL + PAT first', 'err')
            return
        self._busy(True)
        self._set_status('Refreshing uploads…')
        threading.Thread(target=self._refresh_worker, daemon=True).start()

    def _refresh_worker(self):
        try:
            uploads = self.client.list_uploads(per_page=100)
            rows = []
            for up in uploads:
                uid = up.get('upload_id', up.get('id', ''))
                if not uid:
                    continue
                name = up.get('upload_name') or f'Upload {uid[:8]}'
                created = (up.get('upload_create_time', '') or '')[:10]
                # entries field is a COUNT (int); fetch the real list
                entries = []
                try:
                    entries = self.client.list_upload_entries(uid) or []
                except NomadApiError as e:
                    self._log(f'  entries {uid[:8]}: {e}', 'warn')
                tga_entries = []
                for e in entries:
                    md = e.get('entry_metadata') or {} if isinstance(e, dict) else {}
                    if 'TgaMeasurement' in str(md.get('entry_type', '')):
                        tga_entries.append(md)
                if not tga_entries:
                    continue  # only show uploads with TGA schema entries
                files = []
                try:
                    files = self.client.list_raw_files(uid) or []
                except NomadApiError as e:
                    self._log(f'  rawdir {uid[:8]}: {e}', 'warn')
                fnames = []
                for f in files:
                    if isinstance(f, dict):
                        fnames.append(f.get('path', f.get('name', '')))
                    else:
                        fnames.append(str(f))
                has_tprc = any(str(f).lower().endswith('.tprc') for f in fnames)
                has_tri = any(str(f).lower().endswith(('.tri', '.xlsx')) for f in fnames)
                # Auto-mark 'measured' if a .tri exists and no manual status set
                if has_tri and self._manual_status(uid) is None and self.config.get('auto_mark_measured', True):
                    self.config.setdefault('sample_status', {})[uid] = \
                        {'status': 'measured', 'ts': datetime.now().isoformat(timespec='seconds')}
                sample = ''
                if tga_entries:
                    ed = tga_entries[0].get('data') or {}
                    sample = str(ed.get('sample', {}).get('sample_name', ''))[:24]
                rows.append({
                    'upload_id': uid, 'name': name, 'sample': sample,
                    'has_tprc': has_tprc, 'has_tri': has_tri,
                    'entries': len(tga_entries), 'created': created,
                })
                self._upload_cache[uid] = up
                for f in fnames:
                    base = str(f)
                    if base.lower().endswith('.tprc'):
                        self._file_owner[base] = uid
            self._ui(self._render_rows, rows)
            self._log(f'Refresh: {len(rows)} TGA upload(s) found', 'ok')
            self._set_status(f'{len(rows)} TGA uploads', ok=True)
        except NomadApiError as e:
            self._log(f'Refresh failed: {e}', 'err')
            self._set_status('Refresh failed', ok=False)
        except Exception as e:
            self._log(f'Refresh error: {e}', 'err')
            self._set_status('Refresh error', ok=False)
        finally:
            self._busy(False)

    def _render_rows(self, rows):
        self._last_rows = {r['upload_id']: r for r in rows}
        self.upload_tree.delete(*self.upload_tree.get_children())
        for r in rows:
            uid = r['upload_id']
            status = self._display_status(uid, r['has_tri'])
            meta = STATUS_META[status]
            self.upload_tree.insert('', tk.END, iid=uid, tags=(meta['tag'],),
                                    values=(meta['label'], r['name'], r['sample'],
                                            '✓' if r['has_tprc'] else '—',
                                            '✓' if r['has_tri'] else '—',
                                            r['entries'], r['created']))
        for status, meta in STATUS_META.items():
            self.upload_tree.tag_configure(meta['tag'],
                                           foreground=meta['fg'], background=meta['bg'])


    # ── Download .tprc ──────────────────────────────────────────

    def _selected_upload_id(self):
        sel = self.upload_tree.selection()
        return sel[0] if sel else None

    def _download_tprc(self):
        uid = self._selected_upload_id()
        if not uid:
            messagebox.showwarning('No Selection',
                                   'Select an upload in the list first, then try again.')
            return
        import_dir = Path(self.config.get('trios_import_dir', ''))
        if not import_dir.exists():
            messagebox.showerror('Folder Not Found',
                                 f'TRIOS import folder does not exist:\n{import_dir}\n\n'
                                 'Set it in the Configuration tab.')
            return
        self._busy(True)
        threading.Thread(target=self._download_worker, args=(uid, import_dir), daemon=True).start()

    def _download_worker(self, uid, import_dir):
        try:
            files = self.client.list_raw_files(uid) or []
            tprc_files = []
            for f in files:
                fname = f.get('path', f.get('name', '')) if isinstance(f, dict) else str(f)
                if str(fname).lower().endswith('.tprc'):
                    tprc_files.append(fname)
            if not tprc_files:
                self._log('No .tprc file in this upload', 'warn')
                self._set_status('No .tprc in upload', ok=False)
                return
            saved = []
            for rel in tprc_files:
                dest = import_dir / Path(rel).name
                n = self.client.download_raw(uid, rel, str(dest))
                self._file_owner[dest.name] = uid
                self._log(f'Downloaded {Path(rel).name} ({n} B) → {dest}', 'ok')
                saved.append(str(dest))
            self._set_status(f'Saved {len(saved)} .tprc', ok=True)
            messagebox.showinfo('Done', '.tprc saved to:\n' + '\n'.join(saved))
        except NomadApiError as e:
            self._log(f'Download failed: {e}', 'err')
            self._set_status('Download failed', ok=False)
        except Exception as e:
            self._log(f'Download error: {e}', 'err')
            self._set_status('Download error', ok=False)
        finally:
            self._busy(False)

    # ── Upload .tri result ──────────────────────────────────────

    def _upload_tri(self):
        uid = self._selected_upload_id()
        filepath = filedialog.askopenfilename(
            title='Select .tri / .xlsx result file',
            filetypes=[('TRI/Excel files', '*.tri *.xlsx'), ('All files', '*.*')])
        if not filepath:
            return
        if not uid:
            messagebox.showwarning('No Selection',
                                   'Select the upload this result belongs to, then retry.')
            return
        self._busy(True)
        threading.Thread(target=self._upload_worker, args=(uid, filepath), daemon=True).start()

    def _upload_worker(self, uid, filepath):
        try:
            fname = Path(filepath).name
            self._log(f'Uploading {fname} → {uid}', 'info')
            self.client.upload_raw(uid, fname, filepath)
            self._log(f'Uploaded {fname}', 'ok')
            self._set_status('Uploaded, triggering processing…', ok=True)
            try:
                self.client.trigger_process(uid)
                self._log('Processing triggered — NOMAD parses the .tri', 'ok')
            except NomadApiError as e:
                self._log(f'Upload OK, but process trigger failed: {e}', 'warn')
            self._refresh_uploads()
        except NomadApiError as e:
            self._log(f'Upload failed: {e}', 'err')
            self._set_status('Upload failed', ok=False)
        except Exception as e:
            self._log(f'Upload error: {e}', 'err')
            self._set_status('Upload error', ok=False)
        finally:
            self._busy(False)

    # ── Watcher ─────────────────────────────────────────────────

    def _start_watcher(self):
        if not self.watcher_active:
            self._toggle_watcher()

    def _toggle_watcher(self):
        if self.watcher_active:
            self.watcher_active = False
            self.watch_status.set('Watcher: stopped')
            self.watch_btn.config(text='▶ Start Watcher')
            self._log('Watcher stopped', 'info')
        else:
            if not self.client:
                messagebox.showerror('Not Connected',
                                     'Enter NOMAD URL + PAT first in the Configuration tab.')
                return
            self.watcher_active = True
            self.watch_status.set('Watcher: running')
            self.watch_btn.config(text='⏸ Stop Watcher')
            threading.Thread(target=self._watcher_loop, daemon=True).start()
            self._log('Watcher started — watching TRIOS export folder', 'ok')

    def _watcher_loop(self):
        while self.watcher_active:
            try:
                self._watch_export_dir()
            except Exception as e:
                self._log(f'Watcher error: {e}', 'warn')
            time.sleep(int(self.config.get('poll_interval', 15)))

    def _watch_export_dir(self):
        export_dir = Path(self.config.get('trios_export_dir', ''))
        if not export_dir.exists():
            return
        current = set(f.name for f in export_dir.glob('*.tri')) | \
                  set(f.name for f in export_dir.glob('*.xlsx'))
        if self._seen_files is None:
            self._seen_files = current
            return
        new_files = current - self._seen_files
        for fname in sorted(new_files):
            fpath = export_dir / fname
            self._log(f'New result file: {fname}', 'ok')
            if not self.config.get('auto_upload', True):
                self._log('  auto-upload disabled — skipping', 'warn')
                continue
            # Map back to the upload that provided the .tprc (same stem)
            stem = Path(fname).stem
            uid = self._file_owner.get(fname) or self._file_owner.get(f'{stem}.tprc')
            if not uid:
                # fall back to the selected upload
                uid = self._selected_upload_id()
            if not uid:
                self._log('  No matching upload — select one and use Upload .tri', 'warn')
                continue
            try:
                self.client.upload_raw(uid, fname, str(fpath))
                self._log(f'  Uploaded {fname} → {uid}', 'ok')
                # Auto-mark 'measured' after a successful .tri upload
                if self._manual_status(uid) is None and self.config.get('auto_mark_measured', True):
                    self._set_status_for(uid, 'measured')
                try:
                    self.client.trigger_process(uid)
                    self._log('  Processing triggered', 'ok')
                except NomadApiError as e:
                    self._log(f'  Process trigger failed: {e}', 'warn')
            except NomadApiError as e:
                self._log(f'  Upload failed for {fname}: {e}', 'err')
        self._seen_files = current

    # ── Config / misc ───────────────────────────────────────────

    def _browse(self, key, var):
        path = filedialog.askdirectory(title='Select folder')
        if path:
            var.set(path)

    def _save_config(self):
        try:
            for key, var in self.config_vars.items():
                if key == 'poll_interval':
                    try:
                        self.config[key] = int(var.get())
                    except ValueError:
                        self.config[key] = 15
                else:
                    self.config[key] = var.get().strip()
            self.config['auto_download'] = self.auto_dl_var.get()
            self.config['auto_upload'] = self.auto_up_var.get()
            save_config(self.config)
            self._log('Configuration saved', 'ok')
            self._connect()
        except Exception as e:
            messagebox.showerror('Save Failed', str(e))
            self._log(f'Config save failed: {e}', 'err')

    def _open_folder(self):
        path = self.config.get('trios_export_dir', '')
        if not path:
            messagebox.showwarning('Not Configured',
                                   'No TRIOS export folder configured.\n\nSet it in the Configuration tab.')
            return
        if not Path(path).exists():
            messagebox.showerror('Folder Not Found',
                                 f'Folder does not exist:\n{path}')
            return
        try:
            os.startfile(path)
        except Exception as e:
            self._log(f'Could not open folder: {e}', 'err')

    def _on_close(self):
        self.watcher_active = False
        try:
            self.root.destroy()
        except Exception:
            pass

    def run(self):
        self.root.mainloop()


if __name__ == '__main__':
    app = TgaNomadApp()
    app.run()
