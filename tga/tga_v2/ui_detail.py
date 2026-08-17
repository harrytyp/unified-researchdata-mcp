"""Detail panel: metadata, temperature segments, files (download), NOMAD link."""
from pathlib import Path

from nicegui import ui

from backend import Backend, STATUS_LABELS, STATUSES, i18n
from ui_common import _

on_status_changed = None


def build_detail(backend: Backend, container: ui.column, uid: str | None):
    """Render the detail panel for one upload (or empty state)."""
    container.clear()
    with container:
        if not uid:
            ui.label(_('no_selection'))\
                .classes('text-grey-6 tga-sub p-4')
            return
        r = next((x for x in backend.uploads if x['upload_id'] == uid), None)
        if not r:
            ui.label(_('not_found')).classes('text-grey-6 tga-sub p-4')
            return

        status = backend.display_status(uid, r['has_tri'])
        with ui.column().classes('gap-3 p-4 w-full'):
            # Header: name + status select + NOMAD link
            with ui.row().classes('items-center gap-2 w-full'):
                ui.label(r['sample'] or r['name']).classes(
                    'text-lg font-bold flex-1 tga-title')
                ui.select({s: i18n(backend.config, s) for s in STATUSES},
                          value=status, label=_('status')).classes('w-40') \
                    .on_value_change(lambda e: change_status(backend, uid, e.value))
            with ui.row().classes('items-center gap-2 w-full'):
                nomad_url = nomad_entry_url(backend, uid)
                if nomad_url:
                    ui.link(_('open_nomad'), target=nomad_url,
                            new_tab=True).classes('text-sm')
                else:
                    ui.label(_('nomad_na')).classes('text-xs text-grey-5 tga-sub')
                slot = backend.slot_for(uid)
                if slot:
                    ui.badge(f'Slot {slot}').props('color=deep-purple outline')

            # Metadata
            ui.label(_('metadata')).classes('font-bold text-sm tga-title')
            meta_rows(backend, r)

            # Temperature segments
            segs = r.get('segments') or []
            ui.label(f'{_("segments")} ({len(segs)})').classes('font-bold text-sm tga-title')
            if segs:
                ui.table(
                    rows=[
                        {'n': i + 1,
                         'type': str(s.get('segment_type', '?')),
                         'end': str(s.get('end_temp', '')),
                         'rate': str(s.get('rate', '')),
                         'dur': str(s.get('duration_min', ''))}
                        for i, s in enumerate(segs) if isinstance(s, dict)
                    ],
                    columns=[
                        {'name': 'n', 'label': '#', 'field': 'n', 'align': 'left'},
                        {'name': 'type', 'label': 'Typ', 'field': 'type', 'align': 'left'},
                        {'name': 'end', 'label': 'End-Temp', 'field': 'end', 'align': 'left'},
                        {'name': 'rate', 'label': 'Rate', 'field': 'rate', 'align': 'left'},
                        {'name': 'dur', 'label': 'Dauer', 'field': 'dur', 'align': 'left'},
                    ],
                    row_key='n',
                ).props('dense flat bordered')
            else:
                ui.label(_('no_segments')).classes('text-xs text-grey-6 tga-sub')

            # Files
            ui.label(_('files')).classes('font-bold text-sm tga-title')
            for fname in r.get('files') or []:
                file_row(backend, uid, fname)


def nomad_entry_url(backend: Backend, uid: str) -> str | None:
    """The NOMAD GUI URL for this upload's first TGA entry.

    Format (verified): {base}/gui/user/uploads/upload/id/{upload_id}/entry/id/{entry_id}
    """
    base = (backend.config.get('nomad_url', '') or '').rstrip('/')
    if not base:
        return None
    # The refresh() method stores the entry id on the row if available.
    r = next((x for x in backend.uploads if x['upload_id'] == uid), None)
    entry_id = (r or {}).get('entry_id')
    url = f'{base}/gui/user/uploads/upload/id/{uid}'
    if entry_id:
        url += f'/entry/id/{entry_id}'
    return url


def meta_rows(backend: Backend, r: dict):
    for label, value in (
        ('Procedure', r['procedure'] or '—'),
        ('Author', r['author']),
        ('Entry-Typ', r['entry_type']),
        ('Upload-ID', r['upload_id']),
    ):
        with ui.row().classes('gap-2 w-full'):
            ui.label(label).classes('text-xs text-grey-5 tga-sub w-24')
            ui.label(str(value)).classes('text-sm truncate flex-1 tga-title')


def file_row(backend: Backend, uid: str, fname: str):
    lower = fname.lower()
    with ui.row().classes('items-center gap-2 w-full'):
        ui.icon('description').classes('text-grey-6')
        ui.label(fname).classes('text-sm truncate flex-1 tga-title')
        is_tri = lower.endswith(('.tri', '.xlsx'))
        badge = 'positive' if (is_tri and row_has_tri(backend, uid)) else (
            'positive' if lower.endswith('.tprc') else 'warning')
        ui.badge(_('uploaded') if is_tri else _('ready')).props(f'color={badge} outline').classes('text-xs')

        async def download(f=fname):
            try:
                data = await ui.run.io_bound(backend.client.download_raw_bytes, uid, f)
                ui.download.content(bytes(data), Path(f).name)
            except Exception as e:
                ui.notify(f'Download fehlgeschlagen: {e}', type='negative')

        ui.button('', on_click=download).props('icon=download flat round dense')


def row_has_tri(backend: Backend, uid: str) -> bool:
    r = next((x for x in backend.uploads if x['upload_id'] == uid), None)
    return bool(r and r['has_tri'])


def change_status(backend: Backend, uid: str, status: str):
    backend.set_status(uid, status)
    ui.notify(f'{_("status_to")}{i18n(backend.config, status)}', type='positive')
    if on_status_changed:
        on_status_changed()
