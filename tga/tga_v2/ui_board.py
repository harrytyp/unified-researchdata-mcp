"""Kanban board: 4 status columns, cards, HTML5 drag & drop."""
from nicegui import ui

from backend import Backend, STATUSES, STATUS_LABELS
from ui_common import (STATUS_COLORS,
                       NUM_SLOTS, selected, toggle_select, column_header, _)

# Callbacks set by main.py (avoid circular import)
on_open_detail = None       # fn(upload_id)
on_selection_change = None  # fn() — selection changed (action bar update)
on_status_changed = None    # fn()


def build_board(backend: Backend, container: ui.column):
    """Build the full board inside the given container (refreshable body)."""
    container.clear()
    with container:
        with ui.row().classes('gap-3 p-3 items-stretch overflow-x-auto w-full'):
            for status in STATUSES:
                # The WHOLE column is the drop target (not just col_body which
                # is only as tall as its content — empty columns were ~0px).
                with ui.column().classes(
                        'w-72 min-w-72 rounded-xl bg-gray-100 tga-col '
                        'p-2 flex-1 min-h-[300px]') as col_outer:
                    build_column_header(backend, status)
                    with ui.scroll_area().classes('h-[calc(100vh-260px)] w-full'):
                        with ui.column().classes('gap-2 w-full') as col_body:
                            build_column_body(backend, status, col_body)
                    make_column_drop_target(backend, status, col_outer)


def build_column_header(backend: Backend, status: str):
    rows = [r for r in backend.uploads if backend.display_status(
        r['upload_id'], r['has_tri']) == status]
    color = STATUS_COLORS[status]
    with ui.row().classes('items-center gap-2 px-1 w-full'):
        ui.badge(len(rows)).props(f'color={color}').classes('text-xs')
        ui.label(column_header(backend.config, status)).classes(
            'font-bold text-sm flex-1 tga-title')
        if status == 'assigned':
            filled = sum(1 for r in backend.uploads
                         if backend.slot_for(r['upload_id']))
            ui.linear_progress(value=filled / NUM_SLOTS, show_value=False) \
                .classes('w-16').props('color=deep-purple')
            ui.label(f'{filled}/{NUM_SLOTS}').classes('text-xs text-grey-6 tga-sub')


def build_column_body(backend: Backend, status: str, col_body=None):
    """Cards for one column. The 'assigned' column shows the same cards,
    sorted by slot number with a #slot badge — no tiny grid (the 30-slot
    mini-grid was ~45px per cell and useless)."""
    if col_body is not None:
        col_body.clear()
        ctx = col_body
    else:
        ctx = None  # use the ambient slot (during initial build)

    if status == 'assigned':
        # Queue first (assigned but no slot yet), then slotted cards sorted.
        queued = [r for r in backend.uploads
                  if backend.display_status(r['upload_id'], r['has_tri']) == 'assigned'
                  and not backend.slot_for(r['upload_id'])]
        slotted = [r for r in backend.uploads
                   if backend.display_status(r['upload_id'], r['has_tri']) == 'assigned'
                   and backend.slot_for(r['upload_id'])]
        slotted.sort(key=lambda r: int(backend.slot_for(r['upload_id']) or 0))
        if queued:
            ui.label(_('queue_no_slot')).classes(
                'text-xs text-grey-5 tga-sub px-1 w-full')
            for r in queued:
                make_card(backend, r, ctx)
        for r in slotted:
            make_card(backend, r, ctx)
        return

    rows = [r for r in backend.uploads if backend.display_status(
        r['upload_id'], r['has_tri']) == status]
    for r in rows:
        make_card(backend, r, ctx)


def make_card(backend: Backend, r: dict, parent=None):
    """One sample card. Click → detail, drag → move between columns.

    NOTE: the card is a raw ``ui.element('div')`` because HTML5 drag & drop
    requires the ``draggable`` attribute on a plain DOM element — Quasar
    components (ui.card) do not reliably forward it.
    """
    uid = r['upload_id']
    status = backend.display_status(uid, r['has_tri'])
    color = STATUS_COLORS[status]
    is_sel = uid in selected

    ctx = parent if parent is not None else ui
    with ctx:
        with ui.element('div') \
                .props('draggable') \
                .classes('cursor-grab active:cursor-grabbing select-none w-full '
                         'rounded-lg bg-white tga-card border p-2 gap-1 flex flex-col '
                         'shadow-sm hover:shadow-md transition '
                         + ('border-green-500 tga-selected' if is_sel else 'border-grey-3')) as card:
            # dataTransfer carries the upload_id; the drop handler reads it.
            # NOTE: a custom js_handler MUST call emit() or the Python handler
            # is never invoked (NiceGUI contract).
            card.on('dragstart', lambda e: None,
                    js_handler='(e) => { e.dataTransfer.setData("text/plain", "%s"); '
                               'e.dataTransfer.effectAllowed = "move"; emit(e); }' % uid)
            card.on('dragend', lambda e: None,
                    js_handler='(e) => { emit(e); }')
            with ui.row().classes('items-center gap-1 w-full'):
                ui.element('div').classes(
                    f'w-1.5 self-stretch rounded bg-{color}-400')
                # Only the title opens the detail — the selection button below
                # is a separate click target, so no bubbling conflicts.
                ui.label(r['sample'] or r['name']) \
                    .classes('font-bold text-sm truncate flex-1 tga-title cursor-pointer') \
                    .on('click', lambda s=uid: open_detail(s)) \
                    .tooltip(_('details_tooltip'))
                slot = backend.slot_for(uid)
                if slot:
                    ui.badge(f'#{slot}').props('color=deep-purple outline').classes('text-xs')
                # Selection toggle (separate click target on the card).
                def do_select():
                    toggle_select(uid)
                    if on_selection_change:
                        on_selection_change()
                with ui.button('', on_click=do_select) \
                        .props('flat round dense padding=xs').classes('p-0 w-6 h-6'):
                    with ui.icon('check_circle' if is_sel else 'radio_button_unchecked') \
                            .classes('text-green-600' if is_sel else 'text-grey-5 tga-sub'):
                        pass
            ui.label(r['procedure'] or '—').classes(
                'text-xs truncate w-full text-grey-6 tga-sub')
            with ui.row().classes('items-center gap-2 w-full'):
                ui.label(r['author']).classes(
                    'text-xs truncate flex-1 text-grey-5 tga-sub')
                ui.icon('download', color='green' if r['has_tprc'] else 'grey-4').classes('text-sm')
                ui.icon('task_alt', color='green' if r['has_tri'] else 'grey-4').classes('text-sm')


def open_detail(uid: str):
    if on_open_detail:
        on_open_detail(uid)


def make_column_drop_target(backend: Backend, status: str, col_body):
    """Drop on the column background = status change (no slot)."""
    col_body.on('dragover.prevent', lambda: None)
    col_body.on('drop.prevent',
                lambda e: handle_column_drop(backend, status, (e.args or {}).get('uid')),
                js_handler='(e) => emit({ uid: e.dataTransfer.getData("text/plain") })')


def handle_column_drop(backend: Backend, status: str, uid: str | None = None):
    if not uid:
        ui.notify(_('no_upload_id'), type='warning')
        return
    if status == 'assigned':
        # Already in a slot? Keep it (no surprise relocation). Only cards
        # WITHOUT a slot get auto-assigned to the lowest free one.
        if backend.slot_for(uid):
            ui.notify(f'{uid[:8]} {_("stays_slot")} {backend.slot_for(uid)}', type='info')
            return
        used = {backend.slot_for(r['upload_id'])
                for r in backend.uploads if backend.slot_for(r['upload_id'])}
        for n in range(1, NUM_SLOTS + 1):
            label = f'{n:02d}'
            if label not in used:
                backend.assign_slot(uid, label)
                ui.notify(f'{uid[:8]} → Slot {label} {_("to_slot_auto")}', type='positive')
                break
        else:
            ui.notify(_('pan_full'), type='negative')
            return
    else:
        backend.set_status(uid, status)
        ui.notify(f'{uid[:8]} → {STATUS_LABELS[status]}', type='positive')
    if on_status_changed:
        on_status_changed()
