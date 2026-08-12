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
    'dark_mode': False,            # dark palette overlay
    'ui_style': 'modern',          # classic | modern | dark | contrast
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

# ─── UI Theme: semantic color tokens (light + dark) ─────────────

THEMES = {
    'light': {
        'bg': '#f8fafc', 'surface': '#ffffff', 'ink': '#0f172a', 'fg': '#1e293b',
        'muted': '#64748b', 'border': '#e2e8f0', 'heading_bg': '#eef2f7',
        'accent': '#2563eb', 'accent_hover': '#1d4ed8', 'accent_dis': '#93c5fd',
        'on_accent': '#ffffff',
        'ok': '#16a34a', 'warn': '#d97706', 'err': '#dc2626',
        'selection': '#dbeafe', 'selection_fg': '#0f172a',
        'log_bg': '#0f172a', 'log_fg': '#e2e8f0',
        'log_ok': '#4ade80', 'log_warn': '#fbbf24', 'log_err': '#f87171',
    },
    'dark': {
        'bg': '#0f172a', 'surface': '#1e293b', 'ink': '#f8fafc', 'fg': '#e2e8f0',
        'muted': '#94a3b8', 'border': '#334155', 'heading_bg': '#1e293b',
        'accent': '#3b82f6', 'accent_hover': '#2563eb', 'accent_dis': '#1e3a8a',
        'on_accent': '#ffffff',
        'ok': '#4ade80', 'warn': '#fbbf24', 'err': '#f87171',
        'selection': '#1d4ed8', 'selection_fg': '#ffffff',
        'log_bg': '#020617', 'log_fg': '#e2e8f0',
        'log_ok': '#4ade80', 'log_warn': '#fbbf24', 'log_err': '#f87171',
    },
}

# ─── UI styles (tab design + palette) ───────────────────────────

STYLES = {
    'classic': {'label': 'Classic (notebook tabs)', 'tab': 'classic', 'theme': 'light'},
    'modern': {'label': 'Modern (underline tabs)', 'tab': 'underline', 'theme': 'light'},
    'dark': {'label': 'Dark Modern (pill tabs)', 'tab': 'pill', 'theme': 'dark'},
    'contrast': {'label': 'Segment (high contrast)', 'tab': 'segment', 'theme': 'dark'},
}


def resolve_ui(ui_style, dark_mode):
    """→ (color tokens, tab mode). dark_mode overrides to dark palette."""
    s = STYLES.get(ui_style, STYLES['modern'])
    dark = dark_mode or s['theme'] == 'dark'
    return THEMES['dark' if dark else 'light'], s['tab']


def apply_theme(root, c=None):
    c = c or THEMES['light']
    style = ttk.Style(root)
    try:
        style.theme_use('clam')
    except Exception:
        pass
    style.configure('.', font=('Segoe UI', 10), background=c['bg'], foreground=c['fg'])
    style.configure('TNotebook', background=c['bg'], borderwidth=0)
    style.configure('TNotebook.Tab', padding=(12, 6), font=('Segoe UI', 10))
    style.map('TNotebook.Tab', background=[('selected', c['surface'])])
    style.configure('TFrame', background=c['bg'])
    style.configure('Card.TFrame', background=c['surface'], relief='flat')
    style.configure('TLabel', background=c['bg'], foreground=c['fg'])
    style.configure('Card.TLabel', background=c['surface'], foreground=c['fg'])
    style.configure('Muted.TLabel', background=c['surface'], foreground=c['muted'])
    style.configure('MutedBg.TLabel', background=c['bg'], foreground=c['muted'])
    style.configure('Header.TLabel', background=c['bg'], foreground=c['ink'],
                    font=('Segoe UI', 14, 'bold'))
    style.configure('TButton', padding=(10, 6), relief='flat', background=c['surface'], foreground=c['fg'])
    style.map('TButton',
              background=[('active', c['heading_bg']), ('pressed', c['border'])],
              foreground=[('disabled', c['muted'])])
    style.configure('Accent.TButton', padding=(12, 7), background=c['accent'],
                    foreground=c['on_accent'], font=('Segoe UI', 10, 'bold'))
    style.map('Accent.TButton',
              background=[('active', c['accent_hover']), ('disabled', c['accent_dis'])])
    style.configure('Treeview', background=c['surface'], fieldbackground=c['surface'],
                    foreground=c['fg'], rowheight=26, borderwidth=0)
    style.configure('Treeview.Heading', font=('Segoe UI', 10, 'bold'),
                    background=c['heading_bg'], foreground=c['fg'])
    # Selection: keep per-row tag colors — use !selected negation so selected
    # rows get NO foreground from the map -> tag color wins (verified in Tk 8.6).
    style.map('Treeview',
              background=[('selected', c['selection'])],
              foreground=[('!selected', c['ink'])])
    style.configure('TEntry', fieldbackground=c['surface'], foreground=c['fg'],
                    bordercolor=c['border'], padding=4)
    style.configure('TCombobox', fieldbackground=c['surface'], background=c['surface'],
                    foreground=c['fg'], bordercolor=c['border'], arrowcolor=c['fg'])
    style.configure('TCheckbutton', background=c['bg'], foreground=c['fg'])
    style.configure('Vertical.TScrollbar', background=c['border'],
                    troughcolor=c['bg'], borderwidth=0, arrowcolor=c['fg'])
    style.configure('Horizontal.TProgressbar', troughcolor=c['border'], background=c['accent'])


# ─── Sample status model ────────────────────────────────────────

def _status_meta(c):
    return {
        'pending':  {'label': '○ pending',  'tag': 'st_pending',  'fg': c['muted'], 'bg': c['surface']},
        'received': {'label': '● received', 'tag': 'st_received', 'fg': c['ok'],
                     'bg': '#f0fdf4' if c is THEMES['light'] else '#0b3d2e'},
        'measured': {'label': '◉ measured', 'tag': 'st_measured', 'fg': c['accent'],
                     'bg': '#eff6ff' if c is THEMES['light'] else '#0f2a4a'},
    }


class SlotAssignDialog(tk.Toplevel):
    """Modal dialog: one row per selected upload with a slot-label input.

    Slot labels are free-form (e.g. 'A1', '03', 'P1S03') because the pan
    architecture is device-specific. Auto-fill assigns sequential numbers.
    On OK, returns a list of {'upload_id', 'sample', 'slot'} dicts.
    """

    def __init__(self, master, rows, on_ok, c=None):
        super().__init__(master)
        self.title('Auto-Sampler Slot Assignment')
        self.transient(master)
        self.grab_set()
        self.on_ok = on_ok
        self.c = c or THEMES['light']
        self.configure(bg=self.c['bg'])
        self.entries = []  # [{'upload_id', 'sample', 'var'}]

        head = ttk.Frame(self, padding=8)
        head.pack(fill='x')
        for c, txt in enumerate(('Upload', 'Sample', 'TPRC', 'Slot (e.g. A1, 03)')):
            ttk.Label(head, text=txt, font=('Segoe UI', 9, 'bold')).grid(row=0, column=c, padx=6)

        body = ttk.Frame(self, padding=8)
        body.pack(fill='both', expand=True)
        for i, r in enumerate(rows, start=1):
            ttk.Label(body, text=r['name']).grid(row=i, column=0, sticky='w', padx=6)
            ttk.Label(body, text=r['sample']).grid(row=i, column=1, sticky='w', padx=6)
            ttk.Label(body, text='✓' if r['has_tprc'] else '—',
                      foreground=self.c['ok'] if r['has_tprc'] else self.c['muted'],
                      background=self.c['bg']).grid(row=i, column=2, padx=6)
            var = tk.StringVar()
            ttk.Entry(body, textvariable=var, width=8).grid(row=i, column=3, padx=6)
            self.entries.append({'upload_id': r['upload_id'],
                                 'sample': r['sample'], 'var': var})

        bf = ttk.Frame(self, padding=8)
        bf.pack(fill='x')
        ttk.Button(bf, text='Auto-Fill (01, 02, …)', command=self._auto_fill).pack(side='left', padx=4)
        ttk.Button(bf, text='OK', style='Accent.TButton', command=self._ok).pack(side='left', padx=4)
        ttk.Button(bf, text='Cancel', command=self.destroy).pack(side='left', padx=4)
        self.wait_visibility()
        self.focus_set()

    def _auto_fill(self, start=1, step=1):
        for i, e in enumerate(self.entries):
            e['var'].set(f'{start + i * step:02d}')

    def _ok(self):
        result, seen = [], set()
        for e in self.entries:
            label = e['var'].get().strip()
            if not label:
                messagebox.showwarning('Missing Slots', 'Every row needs a slot label.', parent=self)
                return
            if label in seen:
                messagebox.showwarning('Duplicate Slot', f'Slot "{label}" is assigned twice.', parent=self)
                return
            seen.add(label)
            result.append({'upload_id': e['upload_id'], 'sample': e['sample'], 'slot': label})
        self.on_ok(result)
        self.destroy()


class TabBar(tk.Frame):
    """Custom tab bar replacing the notebook tabs: underline / pill / segment.

    Note: uses tk.Frame (not ttk) because it sets direct background colors
    on labels — ttk widgets only accept colors via styles.
    """

    def __init__(self, master, notebook, tabs, mode='underline', c=None):
        super().__init__(master)
        self.nb = notebook
        self.tabs = tabs
        self.mode = mode
        self.c = c or THEMES['light']
        self._labels = []
        self._bar = None
        self._build()

    def _build(self):
        for w in self.winfo_children():
            w.destroy()
        self.configure(background=self.c['bg'])
        self._labels, self._bar = [], None
        parent = self
        if self.mode == 'segment':
            outer = tk.Frame(self, background=self.c['border'], bd=1)
            outer.pack(fill='x')
            parent = tk.Frame(outer, background=self.c['surface'])
            parent.pack(fill='x', padx=1, pady=1)
        for i, (key, text) in enumerate(self.tabs):
            lbl = tk.Label(parent, text=text, font=('Segoe UI', 10),
                           bg=parent['background'], fg=self.c['muted'],
                           padx=16, pady=6, cursor='hand2')
            lbl.pack(side='left')
            lbl.bind('<Button-1>', lambda e, idx=i: self.select(idx))
            lbl.bind('<Return>', lambda e, idx=i: self.select(idx))
            lbl.bind('<space>', lambda e, idx=i: self.select(idx))
            self._labels.append(lbl)
        if self.mode == 'underline':
            self._bar = tk.Frame(self, height=2, background=self.c['accent'])
            self._bar.pack(fill='x')
        self.select(0)

    def select(self, idx):
        self.nb.select(idx)
        c = self.c
        for i, lbl in enumerate(self._labels):
            sel = (i == idx)
            if self.mode == 'pill':
                lbl.config(bg=c['accent'] if sel else c['bg'],
                           fg=c['on_accent'] if sel else c['muted'])
            elif self.mode == 'segment':
                lbl.config(bg=c['accent'] if sel else c['surface'],
                           fg=c['on_accent'] if sel else c['muted'])
            else:  # underline
                lbl.config(fg=c['fg'] if sel else c['muted'],
                           font=('Segoe UI', 10, 'bold' if sel else 'normal'))
        if self.mode == 'underline' and self._bar is not None:
            self.update_idletasks()
            lbl = self._labels[idx]
            self._bar.place(x=lbl.winfo_x(), y=lbl.winfo_height() + 2,
                            width=lbl.winfo_width())
            self._bar.lift()

    def restyle(self, c):
        self.c = c
        self._build()


# ─── Main Application ───────────────────────────────────────────

class TgaNomadApp:
    def __init__(self):
        self.config = load_config()
        self.client = None
        self.watcher_active = False
        self._seen_files = None
        self._upload_cache = {}   # upload_id -> upload dict
        self._file_owner = {}     # local filename -> upload_id (mapping for .tri)
        self._author_cache = {}   # user_id -> username (filled during refresh)
        self._last_rows = {}      # upload_id -> row dict (for inline status updates)
        self.c, self._tab_mode = resolve_ui(self.config.get('ui_style', 'modern'),
                                            self.config.get('dark_mode', False))
        self.status_meta = _status_meta(self.c)
        self.tab_bar = None
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
            color = {'info': self.c['log_fg'], 'ok': self.c['log_ok'],
                     'warn': self.c['log_warn'], 'err': self.c['log_err']}.get(tag, self.c['log_fg'])
            self.log_area.insert(tk.END, f'[{ts}] {msg}\n', (tag,))
            self.log_area.tag_config(tag, foreground=color)
            self.log_area.see(tk.END)
        self._ui(_do)

    def _set_status(self, text, ok=None):
        def _do():
            self.status_var.set(text)
            color = self.c['ink'] if ok is None else (self.c['ok'] if ok else self.c['err'])
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
        self.root.geometry('1180x640')
        self.root.minsize(980, 540)
        self.root.configure(bg=self.c['bg'])
        self.root.protocol('WM_DELETE_WINDOW', self._on_close)
        apply_theme(self.root, self.c)

        # Header bar
        header = ttk.Frame(self.root, padding=(12, 10))
        header.pack(fill='x')
        ttk.Label(header, text='TGA Pipeline', font=('Segoe UI', 14, 'bold'),
                  style='Header.TLabel').pack(side='left')
        self.status_var = tk.StringVar(value='Not connected')
        self.status_label = ttk.Label(header, textvariable=self.status_var, style='MutedBg.TLabel')
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

        # Custom tab bar (underline/pill/segment) or classic notebook tabs
        self.nb = nb
        if self._tab_mode != 'classic':
            for i in range(3):
                nb.tab(i, state='hidden')
            self.tab_bar = TabBar(self.root, nb,
                                  [('exp', 'Experiments'), ('cfg', 'Configuration'), ('log', 'Log')],
                                  mode=self._tab_mode, c=self.c)
            self.tab_bar.pack(fill='x', padx=10, pady=(10, 0))
        nb.pack(fill='both', expand=True, padx=10, pady=(0, 8))

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
        self.slot_btn = ttk.Button(bf, text='◫ Assign Slots…',
                                   command=self._assign_slots)
        self.slot_btn.pack(side='left', padx=6)
        ttk.Button(bf, text='Open Export Folder', command=self._open_folder).pack(side='left', padx=6)

        self.watch_btn = ttk.Button(bf, text='▶ Start Watcher', command=self._toggle_watcher)
        self.watch_btn.pack(side='right')

        # Uploads table
        lf = ttk.LabelFrame(frame, text='NOMAD Uploads (TgaMeasurement)', padding=6)
        lf.pack(fill='both', expand=True)
        self._check_vars = {}  # upload_id -> BooleanVar
        cols = ('check', 'status', 'name', 'sample', 'entry_type', 'procedure', 'author',
                'tprc', 'tri', 'entries', 'created')
        self.upload_tree = ttk.Treeview(lf, columns=cols, show='headings', height=12,
                                        selectmode='extended')
        headings = {'check': '', 'status': 'Status', 'name': 'Name', 'sample': 'Sample',
                    'entry_type': 'Entry Type', 'procedure': 'Procedure Name',
                    'author': 'Main Author', 'tprc': 'Tprc', 'tri': 'Tri',
                    'entries': 'Entries', 'created': 'Created'}
        widths = {'check': 36, 'status': 95, 'name': 165, 'sample': 115, 'entry_type': 95,
                  'procedure': 135, 'author': 105, 'tprc': 50, 'tri': 50,
                  'entries': 55, 'created': 85}
        for c in cols:
            self.upload_tree.heading(c, text=headings[c])
            self.upload_tree.column(c, width=widths[c],
                                    anchor='center' if c == 'check' else (
                                        'w' if c in ('status', 'name', 'sample', 'procedure', 'author') else 'center'))
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
        ttk.Label(foot, text='●', foreground=self.c['ok'], background=self.c['bg']).pack(side='left')
        ttk.Label(foot, text='received   ', background=self.c['bg'], foreground=self.c['muted']).pack(side='left')
        ttk.Label(foot, text='◉', foreground=self.c['accent'], background=self.c['bg']).pack(side='left')
        ttk.Label(foot, text='measured   ', background=self.c['bg'], foreground=self.c['muted']).pack(side='left')
        ttk.Label(foot, text='✓', foreground=self.c['ok'], background=self.c['bg']).pack(side='left')
        ttk.Label(foot, text='.tprc ready   ', background=self.c['bg'], foreground=self.c['muted']).pack(side='left')
        ttk.Label(foot, text='✓', foreground=self.c['warn'], background=self.c['bg']).pack(side='left')
        ttk.Label(foot, text='.tri uploaded   ', background=self.c['bg'], foreground=self.c['muted']).pack(side='left')
        self.watch_status = tk.StringVar(value='Watcher: stopped')
        ttk.Label(foot, textvariable=self.watch_status, background=self.c['bg'],
                  foreground=self.c['muted']).pack(side='right')

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
            ttk.Label(frame, text=label, background=self.c['bg']).grid(row=i, column=0, sticky='w', pady=5)
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

        # UI preferences: style dropdown + dark mode (applied immediately)
        pref = ttk.Frame(frame)
        pref.grid(row=len(fields) + 1, column=0, columnspan=3, sticky='w', pady=(0, 8))
        ttk.Label(pref, text='UI Style:', background=self.c['bg']).pack(side='left')
        self.style_var = tk.StringVar(value=self.config.get('ui_style', 'modern'))
        style_cb = ttk.Combobox(pref, textvariable=self.style_var, state='readonly', width=28,
                                values=[f"{k} — {v['label']}" for k, v in STYLES.items()])
        style_cb.pack(side='left', padx=8)
        style_cb.bind('<<ComboboxSelected>>', lambda e: self._apply_ui_prefs())
        self.dark_var = tk.BooleanVar(value=self.config.get('dark_mode', False))
        ttk.Checkbutton(pref, text='Dark Mode', variable=self.dark_var,
                        command=self._apply_ui_prefs).pack(side='left', padx=(6, 0))

        ttk.Button(frame, text='Save & Reconnect', style='Accent.TButton',
                   command=self._save_config).grid(row=len(fields) + 2, column=0, columnspan=2, sticky='w', pady=8)

    def _apply_ui_prefs(self):
        """Apply theme/tab style immediately — no restart needed."""
        ui_style = self.style_var.get().split(' — ')[0]
        dark = self.dark_var.get()
        c, tab_mode = resolve_ui(ui_style, dark)
        self.c = c
        self._tab_mode = tab_mode
        self.status_meta = _status_meta(c)
        self.config['ui_style'], self.config['dark_mode'] = ui_style, dark

        apply_theme(self.root, c)
        self.root.configure(bg=c['bg'])
        self.log_area.configure(bg=c['log_bg'], fg=c['log_fg'])
        for tag, color in (('info', c['log_fg']), ('ok', c['log_ok']),
                           ('warn', c['log_warn']), ('err', c['log_err'])):
            self.log_area.tag_config(tag, foreground=color)
        # Refresh treeview status tag colors
        for status, meta in self.status_meta.items():
            self.upload_tree.tag_configure(meta['tag'],
                                           foreground=meta['fg'], background=meta['bg'])
        if self._last_rows:
            self._render_rows(list(self._last_rows.values()))

        if tab_mode == 'classic':
            for i in range(3):
                self.nb.tab(i, state='normal')
            if self.tab_bar is not None:
                self.tab_bar.destroy()
                self.tab_bar = None
        else:
            for i in range(3):
                self.nb.tab(i, state='hidden')
            if self.tab_bar is None:
                self.tab_bar = TabBar(self.root, self.nb,
                                      [('exp', 'Experiments'), ('cfg', 'Configuration'), ('log', 'Log')],
                                      mode=tab_mode, c=c)
                self.tab_bar.pack(fill='x', padx=10, pady=(10, 0))
            else:
                self.tab_bar.mode = tab_mode
                self.tab_bar.restyle(c)
        try:
            save_config(self.config)
        except Exception as e:
            self._log(f'Could not save UI prefs: {e}', 'err')
        self._log(f'Style: {ui_style} ({"dark" if dark else "light"})', 'ok')

    def _build_log_tab(self):
        frame = ttk.Frame(self.tab_log, padding=8)
        frame.pack(fill='both', expand=True)
        self.log_area = scrolledtext.ScrolledText(frame, wrap='word', height=16,
                                                  font=('Consolas', 9),
                                                  bg=self.c['log_bg'], fg=self.c['log_fg'])
        self.log_area.pack(fill='both', expand=True)
        for tag, color in (('info', self.c['log_fg']), ('ok', self.c['log_ok']),
                           ('warn', self.c['log_warn']), ('err', self.c['log_err'])):
            self.log_area.tag_config(tag, foreground=color)

    # ── Entry metadata helpers ─────────────────────────────────

    def _procedure_label(self, ed):
        """procedure_name, else derived description from segments, else empty."""
        name = ed.get('procedure_name')
        if name:
            return str(name)[:60]
        segs = ed.get('temperature_segments') or []
        if segs:
            kinds = ', '.join(str(s.get('segment_type', '?')) for s in segs if isinstance(s, dict))
            return f'{len(segs)} Seg: {kinds}'
        return ''

    def _author_name(self, md, upload):
        """Resolve user_id -> real name from entry_metadata.main_author.name.

        Verified: GET /uploads/{id}/entries returns main_author as an object
        {'user_id': ..., 'name': 'Kolja Knodel'} — no extra API call needed.
        Falls back to authors[0], cache, then 'unknown (<id>…)'.
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
            name = self._author_cache.get(user_id, '')
        if not name:
            name = f'unknown ({user_id[:8]}…)' if user_id else 'unknown'
        else:
            self._author_cache[user_id] = name
        return name

    # ── Sample status helpers ──────────────────────────────────

    def _manual_status(self, uid):
        """Manually set status or None."""
        st = (self.config.get('sample_status') or {}).get(uid)
        if isinstance(st, dict):
            return st.get('status') if st.get('status') in self.status_meta else None
        return st if st in self.status_meta else None

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
        meta = self.status_meta[self._display_status(uid, r['has_tri'])]
        # Only touch the status cell + tags — the checkbox widget in column 0
        # must stay untouched (setting 'values' would shift columns).
        self.upload_tree.item(uid, tags=(meta['tag'],))
        self.upload_tree.set(uid, 'status', meta['label'])

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
                entry_type = ''
                procedure = ''
                author = ''
                if tga_entries:
                    md0 = tga_entries[0]
                    ed = md0.get('data') or {}
                    sample = str((ed.get('sample') or {}).get('sample_name', ''))[:24]
                    entry_type = str(md0.get('entry_type') or 'TgaMeasurement')
                    procedure = self._procedure_label(ed)
                    author = self._author_name(md0, up)
                # Prefer a human-meaningful name over the upload's own name
                # (usually unset for ELN-created uploads) or the raw ID.
                name = up.get('upload_name') or sample or procedure or f'Upload {uid[:8]}'
                rows.append({
                    'upload_id': uid, 'name': name, 'sample': sample,
                    'entry_type': entry_type, 'procedure': procedure, 'author': author,
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
        # Keep selection across refresh
        prev_sel = set(self.upload_tree.selection())
        self.upload_tree.delete(*self.upload_tree.get_children())
        self._check_vars = {}
        for r in rows:
            uid = r['upload_id']
            status = self._display_status(uid, r['has_tri'])
            meta = self.status_meta[status]
            var = tk.BooleanVar(value=uid in prev_sel)
            self._check_vars[uid] = var
            cb = ttk.Checkbutton(self.upload_tree, variable=var,
                                 command=lambda i=uid: self._on_check_toggle(i),
                                 takefocus=False)
            self.upload_tree.insert('', tk.END, iid=uid, tags=(meta['tag'],),
                                    values=(cb, meta['label'], r['name'], r['sample'],
                                            r['entry_type'], r['procedure'], r['author'],
                                            '✓' if r['has_tprc'] else '—',
                                            '✓' if r['has_tri'] else '—',
                                            r['entries'], r['created']))
        for status, meta in self.status_meta.items():
            self.upload_tree.tag_configure(meta['tag'],
                                           foreground=meta['fg'], background=meta['bg'])
        if prev_sel:
            self.upload_tree.selection_set(*sorted(prev_sel))

    def _on_check_toggle(self, uid):
        """Keep native selection in sync with the checkbox column."""
        if uid not in self._check_vars:
            return
        if self._check_vars[uid].get():
            self.upload_tree.selection_add(uid)
        else:
            self.upload_tree.selection_remove(uid)


    # ── Download .tprc ──────────────────────────────────────────

    def _selected_upload_ids(self):
        """All selected upload IDs (multi-select via checkboxes or shift+click)."""
        return list(self.upload_tree.selection())

    def _selected_upload_id(self):
        sel = self.upload_tree.selection()
        return sel[0] if sel else None

    def _download_tprc(self):
        uids = self._selected_upload_ids()
        if not uids:
            messagebox.showwarning('No Selection',
                                   'Select at least one upload (checkbox or click), then try again.')
            return
        import_dir = Path(self.config.get('trios_import_dir', ''))
        if not import_dir.exists():
            messagebox.showerror('Folder Not Found',
                                 f'TRIOS import folder does not exist:\n{import_dir}\n\n'
                                 'Set it in the Configuration tab.')
            return
        self._busy(True)
        threading.Thread(target=self._download_worker, args=(uids, import_dir), daemon=True).start()

    def _download_worker(self, uids, import_dir):
        try:
            total = 0
            for uid in uids:
                files = self.client.list_raw_files(uid) or []
                tprc_files = []
                for f in files:
                    fname = f.get('path', f.get('name', '')) if isinstance(f, dict) else str(f)
                    if str(fname).lower().endswith('.tprc'):
                        tprc_files.append(fname)
                if not tprc_files:
                    self._log(f'No .tprc file in upload {uid[:8]}', 'warn')
                    continue
                for rel in tprc_files:
                    dest = import_dir / Path(rel).name
                    n = self.client.download_raw(uid, rel, str(dest))
                    self._file_owner[dest.name] = uid
                    self._log(f'Downloaded {Path(rel).name} ({n} B) → {dest}', 'ok')
                    total += 1
            self._set_status(f'Saved {total} .tprc', ok=total > 0)
            if total:
                messagebox.showinfo('Done', f'{total} .tprc file(s) saved to:\n{import_dir}')
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
        uids = self._selected_upload_ids()
        filepath = filedialog.askopenfilename(
            title='Select .tri / .xlsx result file',
            filetypes=[('TRI/Excel files', '*.tri *.xlsx'), ('All files', '*.*')])
        if not filepath:
            return
        if not uids:
            messagebox.showwarning('No Selection',
                                   'Select at least one upload (checkbox or click), then pick a result file.')
            return
        self._busy(True)
        threading.Thread(target=self._upload_worker, args=(uids, filepath), daemon=True).start()

    def _upload_worker(self, uids, filepath):
        try:
            fname = Path(filepath).name
            for uid in uids:
                self._log(f'Uploading {fname} → {uid}', 'info')
                self.client.upload_raw(uid, fname, filepath)
                self._log(f'Uploaded {fname}', 'ok')
                # Auto-mark 'measured' after a successful .tri upload
                if self._manual_status(uid) is None and self.config.get('auto_mark_measured', True):
                    self._set_status_for(uid, 'measured')
                try:
                    self.client.trigger_process(uid)
                    self._log('Processing triggered — NOMAD parses the .tri', 'ok')
                except NomadApiError as e:
                    self._log(f'Upload OK, but process trigger failed: {e}', 'warn')
            self._set_status('Uploaded, triggering processing…', ok=True)
            self._refresh_uploads()
        except NomadApiError as e:
            self._log(f'Upload failed: {e}', 'err')
            self._set_status('Upload failed', ok=False)
        except Exception as e:
            self._log(f'Upload error: {e}', 'err')
            self._set_status('Upload error', ok=False)
        finally:
            self._busy(False)

    # ── Auto-Sampler slot assignment (filename stage) ──────────

    def _assign_slots(self):
        """Open the slot dialog for all selected uploads."""
        uids = self._selected_upload_ids()
        if not uids:
            messagebox.showwarning('No Selection',
                                   'Select at least one upload (checkbox or click) first.')
            return
        rows = []
        for uid in uids:
            r = getattr(self, '_last_rows', {}).get(uid)
            rows.append({
                'upload_id': uid,
                'name': r['name'] if r else uid,
                'sample': r['sample'] if r else '',
                'has_tprc': r['has_tprc'] if r else False,
            })
        SlotAssignDialog(self.root, rows, self._on_slots_confirmed, self.c)

    def _on_slots_confirmed(self, assignments):
        import_dir = Path(self.config.get('trios_import_dir', ''))
        if not import_dir.exists():
            messagebox.showerror('Folder Not Found',
                                 f'{import_dir}\n\nSet it in the Configuration tab.')
            return
        self._busy(True)
        threading.Thread(target=self._slots_worker, args=(assignments, import_dir),
                         daemon=True).start()

    def _slots_worker(self, assignments, import_dir):
        """Download each .tprc and store it as {Sample}_{Slot}.tprc.

        Intermediate stage: the slot is encoded in the FILENAME only (the
        in-file slot GUID is left untouched until the real TRIOS pan GUID
        convention is verified — see docs/autosampler-slots.md).
        """
        ok, failed = [], []
        for a in assignments:
            try:
                uid, sample, slot = a['upload_id'], a['sample'], a['slot']
                files = self.client.list_raw_files(uid) or []
                rel = next((str(f.get('path', f.get('name', ''))) for f in files
                            if str(f.get('path', f.get('name', ''))).lower().endswith('.tprc')), None)
                if not rel:
                    raise RuntimeError('no .tprc in this upload')
                base = sample if sample else f'exp{uid[:8]}'
                new_name = f'{base}_{slot}.tprc'
                tmp = import_dir / f'.tmp_{Path(rel).name}'
                self.client.download_raw(uid, rel, str(tmp))
                dest = import_dir / new_name
                dest.write_bytes(tmp.read_bytes())
                tmp.unlink(missing_ok=True)
                self._file_owner[dest.name] = uid  # .tri result maps back by stem
                self._log(f'Slot {slot}: {dest.name} ready', 'ok')
                ok.append(str(dest))
            except Exception as e:
                self._log(f'Slot assignment failed ({a.get("upload_id", "?")}): {e}', 'err')
                failed.append(str(e))
        self._busy(False)
        self._set_status(f'{len(ok)} TPRC with slot assignment saved', ok=not failed)
        if ok:
            messagebox.showinfo('Done', 'Saved:\n' + '\n'.join(ok) +
                                ('\n\nFailed:\n' + '\n'.join(failed) if failed else ''))

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
                # fall back to the selection — but only if exactly one is selected
                uids = self._selected_upload_ids()
                uid = uids[0] if len(uids) == 1 else None
            if not uid:
                self._log('  No matching upload — select exactly one, or use Upload .tri', 'warn')
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
            self.config['ui_style'] = self.style_var.get().split(' — ')[0]
            self.config['dark_mode'] = self.dark_var.get()
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
