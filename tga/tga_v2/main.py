"""TGA Operator App v2 — NiceGUI.

Run:  python main.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from nicegui import ui, run

from backend import Backend, STATUS_LABELS, save_config
from nomad_client import NomadClient, NomadApiError
import ui_board
import ui_list
import ui_detail
from ui_common import selected, clear_selection, _

backend = Backend()

# ── i18n: all UI strings, resolved via the config language ────
STRINGS = {
    'app_title': {'en': 'TGA Operator', 'de': 'TGA Operator'},
    'tab_board': {'en': 'Board', 'de': 'Board'},
    'tab_list': {'en': 'List', 'de': 'Liste'},
    'tab_settings': {'en': 'Settings', 'de': 'Einstellungen'},
    'tab_log': {'en': 'Log', 'de': 'Log'},
    'dark': {'en': 'Dark', 'de': 'Dunkel'},
    'appearance_lang': {'en': 'Appearance & Language', 'de': 'Darstellung & Sprache'},
    'language': {'en': 'Language', 'de': 'Sprache'},
    'dark_mode': {'en': 'Dark mode', 'de': 'Dunkelmodus'},
    'nomad_conn': {'en': 'NOMAD Connection', 'de': 'NOMAD Verbindung'},
    'nomad_url': {'en': 'NOMAD URL', 'de': 'NOMAD URL'},
    'api_token': {'en': 'API Token (PAT)', 'de': 'API Token (PAT)'},
    'ssl_verify': {'en': 'SSL verify', 'de': 'SSL verify'},
    'auto_dl': {'en': 'Auto-download .tprc', 'de': 'Auto-Download .tprc'},
    'auto_up': {'en': 'Auto-upload .tri', 'de': 'Auto-Upload .tri'},
    'trios_dirs': {'en': 'TRIOS folders', 'de': 'TRIOS Ordner'},
    'import_dir': {'en': 'Import folder (Methods)', 'de': 'Import-Ordner (Methoden)'},
    'export_dir': {'en': 'Export folder (Data)', 'de': 'Export-Ordner (Daten)'},
    'poll_interval': {'en': 'Poll interval (s)', 'de': 'Poll-Intervall (s)'},
    'save': {'en': 'Save', 'de': 'Speichern'},
    'connect_load': {'en': 'Connect + Load', 'de': 'Verbinden + Laden'},
    'saved': {'en': 'Settings saved', 'de': 'Einstellungen gespeichert'},
    'save_failed': {'en': 'Save failed: ', 'de': 'Speichern fehlgeschlagen: '},
    'sync': {'en': 'Syncing…', 'de': 'Sync…'},
    'selected': {'en': 'selected', 'de': 'ausgewählt'},
    'dl_tprc': {'en': '⬇ Load .tprc', 'de': '⬇ .tprc laden'},
    'assign_slots': {'en': '◫ Assign slots', 'de': '◫ Slots zuweisen'},
    'up_tri': {'en': '⬆ Upload .tri', 'de': '⬆ .tri hochladen'},
    'no_tga': {'en': 'No TGA uploads yet — click Sync.', 'de': 'Noch keine TGA-Uploads — Sync klicken.'},
    'filter_ph': {'en': 'Filter (Sample, Procedure, Author)…', 'de': 'Filter (Sample, Procedure, Author)…'},
    'all_statuses': {'en': 'All statuses', 'de': 'Alle Status'},
    'samples': {'en': 'samples', 'de': 'Proben'},
    'click_sort': {'en': 'Click to sort', 'de': 'Klicken zum Sortieren'},
    'details_tooltip': {'en': 'Click for details', 'de': 'Klicken für Details'},
    'metadata': {'en': 'Metadata', 'de': 'Metadaten'},
    'segments': {'en': 'Segments', 'de': 'Segmente'},
    'no_segments': {'en': 'No segments defined.', 'de': 'Keine Segmente hinterlegt.'},
    'files': {'en': 'Files', 'de': 'Dateien'},
    'open_nomad': {'en': 'Open in NOMAD', 'de': 'NOMAD öffnen'},
    'nomad_na': {'en': 'NOMAD link n/a', 'de': 'NOMAD-Link n/a'},
    'no_selection': {'en': 'No sample selected — click a card.', 'de': 'Keine Probe ausgewählt — klicke eine Karte an.'},
    'not_found': {'en': 'Sample not found.', 'de': 'Probe nicht gefunden.'},
    'uploaded': {'en': 'uploaded', 'de': 'hochgeladen'},
    'ready': {'en': 'ready', 'de': 'bereit'},
    'download_failed': {'en': 'Download failed: ', 'de': 'Download fehlgeschlagen: '},
    'status': {'en': 'Status', 'de': 'Status'},
    'queue_no_slot': {'en': 'Queue (no slot)', 'de': 'Queue (ohne Slot)'},
    'debug_mode': {'en': 'Debug mode (demo data)', 'de': 'Debug-Modus (Demo-Daten)'},
    'connect_warn': {'en': 'NOMAD URL + PAT not configured (Settings tab)',
                     'de': 'NOMAD URL + PAT nicht konfiguriert (Einstellungen-Tab)'},
    'connected': {'en': 'Connected to NOMAD', 'de': 'Verbunden mit NOMAD'},
    'conn_failed': {'en': 'Connection failed: ', 'de': 'Verbindung fehlgeschlagen: '},
    'uploads': {'en': 'uploads', 'de': 'Uploads'},
    'no_upload_id': {'en': 'No upload dragged', 'de': 'Kein Upload mitgezogen'},
    'stays_slot': {'en': 'stays in slot', 'de': 'bleibt in Slot'},
    'pan_full': {'en': 'Pan is full (30/30)', 'de': 'Pan ist voll (30/30)'},
    'to_slot_auto': {'en': '(auto)', 'de': '(auto)'},
    'status_to': {'en': 'Status → ', 'de': 'Status → '},
    'downloads_done': {'en': 'Downloads done', 'de': 'Downloads fertig'},
    'dl_failed': {'en': 'failed:', 'de': 'fehlgeschlagen:'},
    'not_enough_slots': {'en': 'Not enough free slots', 'de': _('not_enough_slots')},
    'result_uploaded': {'en': 'Result uploaded + processing triggered',
                        'de': 'Ergebnis hochgeladen + Processing getriggert'},
    'up_failed': {'en': 'upload failed:', 'de': 'Upload fehlgeschlagen:'},
}


# i18n: `_()` lives in ui_common (set_i18n injects STRINGS + language at page
# start); STRINGS is defined here and passed in. The module-level `_` in
# ui_common is the single translation entry point used by all UI modules.


def _load_dark_css():
    """Global dark-mode CSS (NiceGUI uses Quasar's body.body--dark, not
    Tailwind dark: variants — those never apply)."""
    css = Path(__file__).with_name('tga_dark.css').read_text(encoding='utf-8')
    ui.add_head_html(f'<style>{css}</style>')

# Widget references (never attach to the nicegui.ui module — it rejects
# unknown attributes). Stored in a plain dict owned by this module.
refs = {}


def redraw_all():
    """Rebuild board + list + detail after any state change."""
    if 'board_container' in refs:
        build_board_body()
    if 'list_container' in refs:
        build_list_body()
    if refs.get('detail_uid') is not None:
        build_detail_body(refs['detail_uid'])
    update_action_bar()

# ── Refresh (io_bound so the UI never freezes) ─────────────────

async def do_refresh():
    try:
        if 'sync_box' in refs:
            refs['sync_box'].clear()
            with refs['sync_box']:
                ui.spinner(size='sm')
        rows = await run.io_bound(backend.refresh)
        if 'sync_box' in refs:
            refs['sync_box'].clear()
        ui.notify(f'{len(rows)} TGA Uploads', type='positive')
        redraw_all()
    except RuntimeError as e:
        # client deleted (page closed/reloaded) — timers must not crash
        if 'deleted' not in str(e):
            raise

# ── Board ──────────────────────────────────────────────────────

def build_board_body():
    ui_board.build_board(backend, refs['board_container'])

# ── List ───────────────────────────────────────────────────────

def build_list_body():
    ui_list.build_list(backend, refs['list_container'])

# ── Detail ─────────────────────────────────────────────────────

def build_detail_body(uid):
    ui_detail.build_detail(backend, refs['detail_container'], uid)

def open_detail(uid: str):
    refs['detail_uid'] = uid
    build_detail_body(uid)

# ── Action bar (contextual footer) ─────────────────────────────

def update_action_bar():
    n = len(selected)
    if n == 0:
        refs['footer'].set_visibility(False)
        return
    refs['footer'].set_visibility(True)
    refs['footer_label'].set_text(f'{n} {_("selected")}')
    # Determine which actions apply to the selection
    rows = [r for r in backend.uploads if r['upload_id'] in selected]
    statuses = {backend.display_status(r['upload_id'], r['has_tri']) for r in rows}
    all_tprc = all(r['has_tprc'] for r in rows)
    # Download .tprc: always available
    refs['btn_dl'].set_enabled(bool(rows))
    # Slots: only for received/pending (not measured)
    refs['btn_slots'].set_enabled(bool(statuses & {'pending', 'received', 'assigned'}))
    # Upload .tri: only when tprc present and not yet measured
    refs['btn_tri'].set_enabled(all_tprc and bool(statuses - {'measured'}))

async def action_download_tprc():
    for uid in list(selected):
        try:
            await run.io_bound(backend.download_tprc, uid)
        except Exception as e:
            ui.notify(f'Download {uid[:8]} fehlgeschlagen: {e}', type='negative')
    ui.notify(_('downloads_done'), type='positive')
    redraw_all()

async def action_assign_slots():
    """Auto-assign lowest free slots to all received/pending selection."""
    used = {backend.slot_for(r['upload_id'])
            for r in backend.uploads if backend.slot_for(r['upload_id'])}
    free = [f'{n:02d}' for n in range(1, 31) if f'{n:02d}' not in used]
    rows = [r for r in backend.uploads if r['upload_id'] in selected
            and backend.display_status(r['upload_id'], r['has_tri']) != 'measured']
    if len(rows) > len(free):
        ui.notify(_('not_enough_slots'), type='negative')
        return
    assignments = []
    for r, slot in zip(rows, free):
        backend.assign_slot(r['upload_id'], slot)
        assignments.append({'upload_id': r['upload_id'], 'sample': r['sample'], 'slot': slot})
    ok, failed = await run.io_bound(backend.save_slot_files, assignments)
    ui.notify(f'{len(ok)} Proben → Slots {", ".join(free[:len(ok)])}', type='positive')
    clear_selection()
    redraw_all()

async def action_upload_tri():
    result = await ui.run.io_bound(pick_tri_file)
    if not result:
        return
    for uid in list(selected):
        try:
            await run.io_bound(backend.upload_result, uid, result)
        except Exception as e:
            ui.notify(f'Upload {uid[:8]} fehlgeschlagen: {e}', type='negative')
    ui.notify(_('result_uploaded'), type='positive')
    clear_selection()
    redraw_all()

def pick_tri_file():
    """File picker via tkinter (desktop) — returns path or None."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk(); root.withdraw()
        path = filedialog.askopenfilename(
            title='Select .tri / .xlsx result file',
            filetypes=[('TRI/Excel files', '*.tri *.xlsx'), ('All files', '*.*')])
        root.destroy()
        return path
    except Exception:
        return None

# ── Log view ───────────────────────────────────────────────────

def build_log_body():
    if 'log_container' not in refs:
        return
    try:
        refs['log_container'].clear()
    except RuntimeError:
        return  # client deleted
    with refs['log_container']:
        for ts, tag, msg in backend.log_lines[-200:]:
            color = {'info': 'grey-7 dark:text-grey-4', 'ok': 'green-8',
                     'warn': 'orange-8', 'err': 'red-8'}.get(tag, 'grey-7 dark:text-grey-4')
            ui.label(f'[{ts}] {msg}').classes(f'text-{color.split()[0]} text-xs font-mono '
                                              f'{color.split()[1] if len(color.split())>1 else ""}')

# ── Settings tab ───────────────────────────────────────────────

def build_settings():
    cfg = backend.config
    with ui.column().classes('gap-4 p-4 w-full max-w-2xl'):
        with ui.card().classes('w-full gap-3 p-4'):
            ui.label(_('appearance_lang')).classes('font-bold tga-title')
            with ui.row().classes('items-center gap-4'):
                ui.select({'en': 'English', 'de': 'Deutsch'}, value=cfg.get('language', 'en'),
                          label=_('language')).classes('w-40') \
                    .on_value_change(change_language)
                # Dark mode lives in the config (persisted), applied globally.
                ui.switch(_('dark_mode'), value=cfg.get('dark_mode', False)) \
                    .props('color=primary') \
                    .on_value_change(lambda e: set_dark_mode(bool(e.value)))
        with ui.card().classes('w-full gap-3 p-4'):
            ui.label(_('nomad_conn')).classes('font-bold tga-title')
            url_in = ui.input(_('nomad_url'), value=cfg.get('nomad_url', '')).classes('w-full')
            pat_in = ui.input(_('api_token'), value=cfg.get('nomad_pat', '')) \
                .props('type=password').classes('w-full') \
                .tooltip('NOMAD PAT mit uploads:read/write, entries:read + uploads:process')
            with ui.row().classes('items-center gap-2'):
                ui.switch(_('debug_mode'), value=cfg.get('debug_mode', False)) \
                    .props('color=amber') \
                    .on_value_change(lambda e: cfg.update(debug_mode=bool(e.value))) \
                    .tooltip('Demo-Daten statt echtem Server — kein PAT nötig')
            with ui.row().classes('items-center gap-4'):
                ui.switch(_('ssl_verify'), value=cfg.get('verify_ssl', False)).bind_value_to(
                    cfg, 'verify_ssl')
                ui.switch(_('auto_dl'), value=cfg.get('auto_download', True)).bind_value_to(
                    cfg, 'auto_download')
                ui.switch(_('auto_up'), value=cfg.get('auto_upload', True)).bind_value_to(
                    cfg, 'auto_upload')
        with ui.card().classes('w-full gap-3 p-4'):
            ui.label(_('trios_dirs')).classes('font-bold tga-title')
            imp_in = ui.input(_('import_dir'),
                              value=cfg.get('trios_import_dir', '')).classes('w-full')
            exp_in = ui.input(_('export_dir'),
                              value=cfg.get('trios_export_dir', '')).classes('w-full')
            ui.input(_('poll_interval'), value=str(cfg.get('poll_interval', 15))) \
                .classes('w-40').on_value_change(
                    lambda e: cfg.update(poll_interval=int(e.value or 15)))
        with ui.row().classes('gap-2'):
            ui.button(_('save'), on_click=lambda: save_settings(
                url_in, pat_in, imp_in, exp_in)).props('color=primary')
            ui.button(_('connect_load'),
                      on_click=do_refresh).props('icon=cloud_done outline')


def change_language(e):
    """Persist language + rebuild the whole page with the new strings."""
    backend.config['language'] = e.value
    try:
        save_config(backend.config)
    except Exception:
        pass
    ui.navigate.reload()


def set_dark_mode(value: bool):
    """Apply + persist dark mode (config is the single source of truth)."""
    backend.config['dark_mode'] = bool(value)
    try:
        save_config(backend.config)
    except Exception as e:
        ui.notify(f'Dark mode speichern fehlgeschlagen: {e}', type='negative')
    # The page-level dark_mode element toggles the actual theme.
    if 'dark_mode_el' in refs:
        refs['dark_mode_el'].toggle() if value != refs['dark_mode_el'].value else None


def save_settings(url_in, pat_in, imp_in, exp_in):
    cfg = backend.config
    cfg['nomad_url'] = url_in.value.strip()
    if pat_in.value.strip():
        cfg['nomad_pat'] = pat_in.value.strip()  # only overwrite if non-empty
    cfg['trios_import_dir'] = imp_in.value.strip()
    cfg['trios_export_dir'] = exp_in.value.strip()
    try:
        save_config(cfg)
        ui.notify('Einstellungen gespeichert', type='positive')
        connect()
    except Exception as e:
        ui.notify(f'Speichern fehlgeschlagen: {e}', type='negative')


# ── Main page ──────────────────────────────────────────────────

@ui.page('/')
def index():
    _load_dark_css()
    from ui_common import set_i18n
    set_i18n(STRINGS, backend.config.get('language', 'en'))
    # Header
    with ui.header().classes('items-center justify-between px-4'):
        with ui.row().classes('items-center gap-2'):
            ui.icon('science').classes('text-primary')
            ui.label('TGA Operator').classes('text-lg font-bold text-white')
        with ui.row().classes('items-center gap-3'):
            refs['sync_box'] = ui.row().classes('items-center gap-2')
            ui.button('', on_click=do_refresh).props('icon=refresh flat round dense text-white')
            # One global dark-mode element; both header switch and settings
            # write to the config (persisted) and this element applies it.
            refs['dark_mode_el'] = ui.dark_mode(
                value=backend.config.get('dark_mode', False))
            ui.switch('Dark').props('color=primary dark') \
                .bind_value_from(refs['dark_mode_el'], 'value') \
                .on_value_change(lambda e: set_dark_mode(bool(e.value)))

    # Tabs (main area left, detail panel right) — h-screen, no page scroll
    with ui.row().classes('w-full flex-1 items-stretch min-h-0'):
        with ui.column().classes('flex-1 min-w-0 min-h-0'):
            with ui.tabs().classes('w-full') as tabs:
                tab_board = ui.tab(_('tab_board'), icon='view_kanban')
                tab_list = ui.tab(_('tab_list'), icon='view_list')
                tab_settings = ui.tab(_('tab_settings'), icon='settings')
                tab_log = ui.tab(_('tab_log'), icon='terminal')
            with ui.tab_panels(tabs, value=tab_board).classes('w-full flex-1 min-h-0'):
                with ui.tab_panel(tab_board):
                    refs['board_container'] = ui.column().classes('w-full')
                with ui.tab_panel(tab_list):
                    refs['list_container'] = ui.column().classes('w-full')
                with ui.tab_panel(tab_settings):
                    build_settings()
                with ui.tab_panel(tab_log):
                    refs['log_container'] = ui.column().classes('w-full gap-0 p-2')

        # Detail panel: fixed right column
        with ui.column().classes('w-80 min-w-80 border-l border-grey-3 min-h-0'):
            refs['detail_container'] = ui.column().classes('w-full')

    # Action bar (footer, hidden until selection)
    with ui.footer() as footer:
        with ui.row().classes('items-center justify-between px-4 py-2 w-full'):
            with ui.row().classes('items-center gap-3'):
                refs['footer_label'] = ui.label(f'0 {_("selected")}').classes('text-sm font-bold')
                refs['btn_dl'] = ui.button(_('dl_tprc'), on_click=action_download_tprc)
                refs['btn_slots'] = ui.button(_('assign_slots'), on_click=action_assign_slots)
                refs['btn_tri'] = ui.button(_('up_tri'), on_click=action_upload_tri)
            ui.button('', on_click=lambda: (clear_selection(), update_action_bar()))\
                .props('icon=close flat round dense')
    refs['footer'] = footer
    footer.set_visibility(False)

    # Wire callbacks
    ui_board.on_open_detail = open_detail
    ui_board.on_selection_change = update_action_bar
    ui_board.on_status_changed = redraw_all
    ui_list.on_open_detail = open_detail
    ui_list.on_list_selection_cb = update_action_bar
    ui_detail.on_status_changed = redraw_all

    # Connection + initial load
    connect()
    build_log_body()
    update_action_bar()
    # Lock the page height so only the board columns scroll internally
    ui.query('body').classes('overflow-hidden h-screen')
    ui.query('.q-page').classes('h-screen overflow-hidden')
    ui.timer(30.0, do_refresh)
    ui.timer(float(backend.config.get('poll_interval', 15)), watcher_tick)

def watcher_tick():
    try:
        backend.watcher_tick()
        build_log_body()
        redraw_all()
    except RuntimeError as e:
        # client deleted (page closed/reloaded) — timers must not crash
        if 'deleted' not in str(e):
            raise

def connect():
    # Debug mode: demo data (FakeClient), no network, no PAT needed.
    # Enabled via Settings toggle (config.debug_mode) or env TGA_FAKE_CLIENT.
    if backend.config.get('debug_mode') or os.environ.get('TGA_FAKE_CLIENT') == '1':
        from fake_client import FakeClient
        backend.client = FakeClient()
        backend.refresh()
        redraw_all()
        ui.notify('Demo-Modus (FakeClient) aktiv', type='info')
        return
    url = backend.config.get('nomad_url', '')
    pat = backend.config.get('nomad_pat', '')
    if not url or not pat:
        ui.notify('NOMAD URL + PAT nicht konfiguriert (Config-Datei)',
                  type='warning')
        return
    backend.client = NomadClient(url, pat, verify=backend.config.get('verify_ssl', False))
    ok, msg = backend.client.check_health()
    if ok:
        ui.notify('Verbunden mit NOMAD', type='positive')
    else:
        ui.notify(f'Verbindung fehlgeschlagen: {msg}', type='negative')


if __name__ in {'__main__', '__mp_main__'}:
    ui.run(title='TGA Operator',
           dark=backend.config.get('dark_mode', False),
           native=False,
           port=8080,
           reload=False)