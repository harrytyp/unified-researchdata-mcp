"""
tga_elab_app.pyw — Windows Tray App for TGA Pipeline via elabFTW.

Standalone app that:
  - Monitors elabFTW for TGA experiments
  - Downloads .tprc files → TRIOS import folder
  - Monitors TRIOS export folder for .tri files
  - Uploads .tri results back to elabFTW as attachments

Package as .exe: pyinstaller --onefile --noconsole tga_elab_app.pyw
"""
import os, sys, json, time, threading, logging, hashlib
from pathlib import Path
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, filedialog
import requests
import urllib3; urllib3.disable_warnings()

# ─── Configuration ──────────────────────────────────────────────
CONFIG_FILE = Path.home() / '.tga_elab_config.json'
DEFAULT_CONFIG = {
    'elabftw_url': 'https://elntest.ub.tum.de/api/v2',
    'api_key': '',
    'team_id': 29,
    'trigger_field': 'Status',
    'trigger_value': 'Running',
    'trios_import_dir': str(Path.home() / 'TRIOS' / 'Methods'),
    'trios_export_dir': str(Path.home() / 'TRIOS' / 'Data'),
    'auto_download': True,
    'auto_upload': True,
}


def load_config():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                cfg.setdefault(k, v)
            return cfg
    return dict(DEFAULT_CONFIG)


def save_config(cfg):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(cfg, f, indent=2)


# ─── elabFTW Client ─────────────────────────────────────────────

class ElabClient:
    def __init__(self, url, api_key):
        self.url = url.rstrip('/')
        self.headers = {'Authorization': api_key}
    
    def get(self, path):
        r = requests.get(f"{self.url}{path}", headers=self.headers, verify=False, timeout=15)
        return r.json() if r.status_code == 200 else None
    
    def patch(self, path, data):
        r = requests.patch(f"{self.url}{path}", json=data,
                          headers={**self.headers, 'Content-Type': 'application/json'},
                          verify=False, timeout=15)
        return r.status_code in (200, 201)
    
    def upload_file(self, item_id, filepath):
        with open(filepath, 'rb') as f:
            r = requests.post(f"{self.url}/items/{item_id}/uploads",
                            files={'file': (Path(filepath).name, f, 'application/octet-stream')},
                            headers=self.headers, verify=False, timeout=60)
        return r.status_code in (200, 201)
    
    def download_file(self, item_id, upload_id, dest_path):
        r = requests.get(f"{self.url}/items/{item_id}/uploads/{upload_id}",
                        headers=self.headers, verify=False, timeout=30)
        if r.status_code == 200:
            Path(dest_path).write_bytes(r.content)
            return True
        return False
    
    def get_uploads(self, item_id):
        r = requests.get(f"{self.url}/items/{item_id}/uploads",
                        headers=self.headers, verify=False, timeout=15)
        return r.json() if r.status_code == 200 else []
    
    def list_experiments(self, team_id, category=5, limit=20):
        """List recent TGA items."""
        r = requests.get(f"{self.url}/items?team={team_id}&limit={limit}",
                        headers=self.headers, verify=False, timeout=15)
        return r.json() if r.status_code == 200 else []


# ─── TGA Tray Application ───────────────────────────────────────

class TgaElabApp:
    def __init__(self):
        self.config = load_config()
        self.client = None
        self.running = True
        self._build_ui()
        self._connect()
    
    def _connect(self):
        if self.config.get('api_key'):
            self.client = ElabClient(
                self.config['elabftw_url'],
                self.config['api_key']
            )
            self._log("Connected to elabFTW")
    
    def _build_ui(self):
        self.root = tk.Tk()
        self.root.title("TGA elabFTW Agent")
        self.root.geometry("650x550")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        
        nb = ttk.Notebook(self.root)
        nb.pack(fill='both', expand=True, padx=5, pady=5)
        
        # Tab 1: Control
        self.tab_ctrl = ttk.Frame(nb)
        nb.add(self.tab_ctrl, text="Control")
        self._build_control_tab()
        
        # Tab 2: Configuration
        self.tab_config = ttk.Frame(nb)
        nb.add(self.tab_config, text="Configuration")
        self._build_config_tab()
        
        # Tab 3: Log
        self.tab_log = ttk.Frame(nb)
        nb.add(self.tab_log, text="Log")
        self._build_log_tab()
        
        # Start watcher automatically if configured
        if self.client and self.config.get('auto_download'):
            self._start_watcher()
    
    def _build_control_tab(self):
        frame = ttk.Frame(self.tab_ctrl, padding=10)
        frame.pack(fill='both', expand=True)
        
        # Status
        sf = ttk.LabelFrame(frame, text="Status", padding=5)
        sf.pack(fill='x', pady=5)
        
        self.api_status = tk.StringVar(value="Not configured")
        ttk.Label(sf, text="elabFTW:").grid(row=0, column=0, sticky='w')
        ttk.Label(sf, textvariable=self.api_status).grid(row=0, column=1, sticky='w')
        
        # Actions
        bf = ttk.LabelFrame(frame, text="Actions", padding=5)
        bf.pack(fill='x', pady=5)
        
        ttk.Button(bf, text="Refresh Experiments", command=self._refresh_experiments).pack(side='left', padx=3)
        ttk.Button(bf, text="Download .tprc", command=self._download_tprc).pack(side='left', padx=3)
        self.upload_btn = ttk.Button(bf, text="Upload .tri", command=self._upload_tri)
        self.upload_btn.pack(side='left', padx=3)
        ttk.Button(bf, text="Open Export Folder", command=self._open_folder).pack(side='left', padx=3)
        
        # Experiment list
        lf = ttk.LabelFrame(frame, text="TGA Experiments", padding=5)
        lf.pack(fill='both', expand=True, pady=5)
        
        columns = ('ID', 'Title', 'Sample', 'Created', 'Status')
        self.exp_tree = ttk.Treeview(lf, columns=columns, show='headings', height=8)
        for col in columns:
            self.exp_tree.heading(col, text=col)
            self.exp_tree.column(col, width=100)
        self.exp_tree.column('ID', width=50)
        self.exp_tree.column('Status', width=80)
        self.exp_tree.pack(fill='both', expand=True)
        
        # Watcher status
        wf = ttk.LabelFrame(frame, text="Auto Watcher", padding=5)
        wf.pack(fill='x', pady=5)
        
        self.watch_btn = ttk.Button(wf, text="Start Watcher", command=self._toggle_watcher)
        self.watch_btn.pack(side='left', padx=5)
        self.watch_status = tk.StringVar(value="Stopped")
        ttk.Label(wf, textvariable=self.watch_status).pack(side='left', padx=5)
    
    def _build_config_tab(self):
        frame = ttk.Frame(self.tab_config, padding=10)
        frame.pack(fill='both', expand=True)
        
        fields = [
            ('elabFTW URL:', 'elabftw_url'),
            ('API Key:', 'api_key'),
            ('Team ID:', 'team_id'),
            ('Trigger Field:', 'trigger_field'),
            ('Trigger Value:', 'trigger_value'),
            ('TRIOS Import Folder:', 'trios_import_dir'),
            ('TRIOS Export Folder:', 'trios_export_dir'),
        ]
        
        self.config_vars = {}
        for i, (label, key) in enumerate(fields):
            ttk.Label(frame, text=label).grid(row=i, column=0, sticky='w', pady=3)
            if 'Folder' in label:
                var = tk.StringVar(value=str(self.config.get(key, '')))
                entry = ttk.Entry(frame, textvariable=var, width=60)
                entry.grid(row=i, column=1, padx=5, pady=3)
                btn = ttk.Button(frame, text="Browse...",
                               command=lambda k=key, v=var: self._browse(k, v))
                btn.grid(row=i, column=2)
            else:
                var = tk.StringVar(value=str(self.config.get(key, '')))
                if 'key' in key:
                    entry = ttk.Entry(frame, textvariable=var, width=60, show='*')
                else:
                    entry = ttk.Entry(frame, textvariable=var, width=60)
                entry.grid(row=i, column=1, padx=5, pady=3)
            self.config_vars[key] = var
        
        ttk.Button(frame, text="Save & Reconnect", command=self._save_config).grid(
            row=len(fields), column=0, columnspan=2, pady=10)
    
    def _build_log_tab(self):
        frame = ttk.Frame(self.tab_log, padding=10)
        frame.pack(fill='both', expand=True)
        self.log_area = scrolledtext.ScrolledText(frame, height=15, wrap='word')
        self.log_area.pack(fill='both', expand=True)
    
    def _log(self, msg):
        timestamp = datetime.now().strftime('%H:%M:%S')
        line = f"[{timestamp}] {msg}\n"
        if hasattr(self, 'log_area'):
            self.log_area.insert(tk.END, line)
            self.log_area.see(tk.END)
    
    def _refresh_experiments(self):
        if not self.client:
            self._log("❌ No API key configured")
            return
        
        try:
            exps = self.client.list_experiments(self.config['team_id'])
            self.exp_tree.delete(*self.exp_tree.get_children())
            for exp in exps[:30]:
                meta = exp.get('metadata', {})
                fields = meta.get('extra_fields', {}) if isinstance(meta, dict) else {}
                sample = fields.get('sample_name', '') if isinstance(fields, dict) else ''
                self.exp_tree.insert('', tk.END, values=(
                    exp.get('id', ''),
                    exp.get('title', '')[:20],
                    str(sample)[:15],
                    exp.get('created_at', '')[:10] if exp.get('created_at') else '',
                    exp.get('status', '') or '-',
                ))
            self.api_status.set(f"Connected, {len(exps)} experiments")
            self._log(f"✅ Fetched {len(exps)} experiments")
        except Exception as e:
            self._log(f"❌ Error: {e}")
            self.api_status.set("Error")
    
    def _download_tprc(self):
        """Download .tprc from selected experiment → TRIOS import folder."""
        sel = self.exp_tree.selection()
        if not sel:
            messagebox.showwarning("No Selection", "Click an experiment in the list first, then try again.")
            return
        
        item_id = self.exp_tree.item(sel[0], 'values')[0]
        import_dir = Path(self.config.get('trios_import_dir', ''))
        if not import_dir.exists():
            messagebox.showerror("Folder Not Found",
                f"TRIOS import folder not found:\n{import_dir}\n\n"
                "Configure it in the Configuration tab.")
            return
        
        if not self.client:
            messagebox.showerror("Not Connected", "Enter your elabFTW API key in the Configuration tab.")
            return
        
        self._log(f"→ Looking for .tprc in item {item_id}...")
        uploads = self.client.get_uploads(item_id)
        tprc_uploads = [u for u in uploads if isinstance(u, dict) and 
                       (u.get('real_name', '') or u.get('filename', '')).endswith('.tprc')]
        
        if not tprc_uploads:
            msg = ("No .tprc file attached to this experiment yet.\n\n"
                   "Make sure:\n"
                   "1. The experiment status is set to 'Running'\n"
                   "2. The server watcher has run (up to 1 min)\n"
                   "3. Then try Download again")
            messagebox.showinfo("No .tprc", msg)
            return
        
        saved = []
        for up in tprc_uploads:
            fid = up.get('id', up.get('upload_id', ''))
            fname = up.get('real_name', up.get('filename', 'tga.tprc'))
            dest = import_dir / fname
            
            r = requests.get(f"{self.client.url}/items/{item_id}/uploads/{fid}",
                           headers=self.client.headers, verify=False, timeout=30)
            if r.status_code == 200:
                dest.write_bytes(r.content)
                self._log(f"✅ Saved: {dest}")
                saved.append(str(dest))
            else:
                self._log(f"❌ Download failed: HTTP {r.status_code}")
        
        if saved:
            messagebox.showinfo("Done", f".tprc saved to:\n" + "\n".join(saved))
    
    def _upload_tri(self):
        """Upload a .tri file to the selected experiment."""
        sel = self.exp_tree.selection()
        if not sel:
            filepath = filedialog.askopenfilename(
                title="Select .tri file",
                filetypes=[("TRI/Excel files", "*.tri *.xlsx"), ("All files", "*.*")]
            )
            if not filepath:
                return
            # Ask which experiment
            self._log(f"→ Selected file: {Path(filepath).name}")
            self._log("   Select an experiment in the list, then click Upload again")
            return
        
        item_id = self.exp_tree.item(sel[0], 'values')[0]
        filepath = filedialog.askopenfilename(
            title="Select .tri file for item " + item_id,
            filetypes=[("TRI/Excel files", "*.tri *.xlsx"), ("All files", "*.*")]
        )
        if not filepath:
            return
        
        if not self.client:
            self._log("❌ No API key configured")
            return
        
        self._log(f"→ Uploading {Path(filepath).name} to item {item_id}...")
        try:
            ok = self.client.upload_file(item_id, filepath)
            if ok:
                self._log(f"✅ Uploaded to item {item_id}")
            else:
                self._log(f"❌ Upload failed")
        except Exception as e:
            self._log(f"❌ Error: {e}")
    
    def _start_watcher(self):
        """Start the auto-watcher if not already running."""
        if not self.watcher_active:
            self._toggle_watcher()
    
    def _toggle_watcher(self):
        if self.watcher_active:
            self.watcher_active = False
            self.watch_status.set("Stopped")
            self.watch_btn.config(text="Start Watcher")
            self._log("Watcher stopped")
        else:
            if not self.client:
                messagebox.showerror("Not Connected",
                    "Enter your elabFTW API key first in the Configuration tab.")
                return
            self.watcher_active = True
            self.watch_status.set("Running")
            self.watch_btn.config(text="Stop Watcher")
            t = threading.Thread(target=self._watcher_loop, daemon=True)
            t.start()
            self._log("Watcher started — monitoring elabFTW + TRIOS export")
    
    def _watcher_loop(self):
        while self.watcher_active:
            try:
                self._check_elabftw_tprc()
                self._check_trios_export()
            except Exception as e:
                self._log(f"Watcher error: {e}")
            time.sleep(15)
    
    def _check_elabftw_tprc(self):
        """Check for new TGA experiments and generate .tprc if needed."""
        if not self.client:
            return
        cfg = self.config
        trigger_field = cfg.get('trigger_field', 'Status')
        trigger_val = cfg.get('trigger_value', 'Running')
        
        exps = self.client.list_experiments(cfg['team_id'])
        for exp in exps[:20]:
            meta = exp.get('metadata', {})
            fields = meta.get('extra_fields', {}) if isinstance(meta, dict) else {}
            
            # Check if .tprc already attached
            uploads = self.client.get_uploads(exp['id'])
            has_tprc = any(u.get('real_name', '').endswith('.tprc') for u in uploads if isinstance(u, dict))
            
            # Check trigger condition
            status_value = fields.get(trigger_field, '') if isinstance(fields, dict) else ''
            
            if isinstance(fields, dict) and fields.get('sample_name') and not has_tprc:
                self._log(f"  → Need .tprc for item {exp['id']} ({fields.get('sample_name', '')})")
    
    def _check_trios_export(self):
        """Watch TRIOS export folder for new .tri files and upload them."""
        export_dir = Path(self.config.get('trios_export_dir', ''))
        if not export_dir.exists():
            return
        
        if not hasattr(self, '_seen_files'):
            self._seen_files = set(f.name for f in export_dir.glob('*.tri')) | \
                               set(f.name for f in export_dir.glob('*.xlsx'))
            return
        
        # Check for new files
        current_files = set(f.name for f in export_dir.glob('*.tri')) | \
                        set(f.name for f in export_dir.glob('*.xlsx'))
        
        new_files = current_files - self._seen_files
        for fname in new_files:
            fpath = export_dir / fname
            self._log(f"📁 New file detected: {fname}")
            # Try to upload to the most recent experiment
            sel = self.exp_tree.selection()
            if sel:
                item_id = self.exp_tree.item(sel[0], 'values')[0]
                self._log(f"→ Uploading to item {item_id}...")
                try:
                    ok = self.client.upload_file(item_id, str(fpath))
                    if ok:
                        self._log(f"✅ Uploaded {fname}")
                    else:
                        self._log(f"❌ Upload failed for {fname}")
                except Exception as e:
                    self._log(f"❌ Error uploading {fname}: {e}")
            else:
                self._log(f"⚠️ No experiment selected — {fname} not uploaded")
        
        self._seen_files = current_files
    
    def _browse(self, key, var):
        path = filedialog.askdirectory(title=f"Select folder")
        if path:
            var.set(path)
    
    def _save_config(self):
        for key, var in self.config_vars.items():
            if key == 'team_id':
                self.config[key] = int(var.get())
            else:
                self.config[key] = var.get()
        save_config(self.config)
        self._connect()
        self._log("✅ Configuration saved")
    
    def _open_folder(self):
        path = self.config.get('trios_export_dir', '')
        if not path:
            messagebox.showwarning("Not Configured",
                "No TRIOS export folder configured.\n\nSet it in the Configuration tab.")
            return
        if not Path(path).exists():
            messagebox.showerror("Folder Not Found",
                f"The configured export folder does not exist:\n{path}\n\n"
                "Check the path in the Configuration tab.")
            return
        os.startfile(path)
    
    def _on_close(self):
        self.watcher_active = False
        self.running = False
        self.root.destroy()
    
    def run(self):
        self.root.mainloop()


if __name__ == '__main__':
    app = TgaElabApp()
    app.run()
