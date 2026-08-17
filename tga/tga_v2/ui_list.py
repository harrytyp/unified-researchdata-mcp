"""List view: compact rows (no AG Grid — enterprise rowSelection broke it).

Own rows give us: checkboxes, status badges, filtering, sorting — all in
Python, dark-mode safe via tga-* CSS classes, no JavaScript.
"""
from nicegui import ui

from backend import Backend, STATUS_LABELS, i18n
from ui_common import STATUS_COLORS, selected, toggle_select, column_header, _

on_open_detail = None
on_selection_change = None

_sort = ('created', True)  # (field, ascending)


def build_list(backend: Backend, container: ui.column):
    container.clear()
    with container:
        state = {'filter': '', 'status': 'alle'}

        # Toolbar: filter + status filter
        with ui.row().classes('items-center gap-2 w-full px-2 py-1'):
            ui.input(placeholder=_('filter_ph')) \
                .props('icon=search clearable dense') \
                .classes('w-72') \
                .on_value_change(lambda e: (state.update(filter=e.value.lower()),
                                            render_rows(backend, body, state)))
            ui.select({'alle': (_('all_statuses') if backend.config.get('language')=='de' else 'All statuses'),
                    **{s: i18n(backend.config, s) for s in STATUS_LABELS}}, value='alle',
                      label=_('status')).classes('w-44') \
                .on_value_change(lambda e: (state.update(status=e.value),
                                            render_rows(backend, body, state)))
            ui.label(f'{len(backend.uploads)} {_("samples")}').classes(
                'text-sm text-grey-6 tga-sub')

        # Header row (clickable for sorting)
        with ui.row().classes('w-full items-center gap-2 px-2 py-1 font-bold '
                              'text-xs text-grey-7 tga-title '
                              'border-b border-grey-3 tga-row'):
            ui.label('').classes('w-10')
            for field, label, w in (('sample', 'Sample', 'flex-1'),
                                    ('procedure', 'Procedure', 'flex-1'),
                                    ('author', 'Author', 'w-32'),
                                    ('status', 'Status', 'w-32'),
                                    ('slot', 'Slot', 'w-12'),
                                    ('tprc', 'TPRC', 'w-10'),
                                    ('tri', 'TRI', 'w-10'),
                                    ('created', 'Erstellt', 'w-20')):
                header_label = ui.label(label).classes(f'{w} cursor-pointer truncate') \
                    .on('click', lambda f=field: (set_sort(f), render_rows(backend, body, state)))
                header_label.tooltip(_('click_sort'))

        # Rows container
        body = ui.column().classes('w-full gap-0')
        render_rows(backend, body, state)


def set_sort(field):
    global _sort
    if _sort[0] == field:
        _sort = (field, not _sort[1])
    else:
        _sort = (field, True)


def sort_rows(rows):
    field, asc = _sort
    return sorted(rows, key=lambda r: str(r.get(field, '') or '').lower(),
                  reverse=not asc)


def render_rows(backend: Backend, body: ui.column, state):
    body.clear()
    rows = []
    for r in backend.uploads:
        uid = r['upload_id']
        status = backend.display_status(uid, r['has_tri'])
        if state['status'] != 'alle' and status != state['status']:
            continue
        if state['filter']:
            hay = f"{r['sample']} {r['procedure']} {r['author']}".lower()
            if state['filter'] not in hay:
                continue
        rows.append(r)
    for r in sort_rows(rows):
        make_row(backend, r, body, state)


def make_row(backend: Backend, r: dict, body: ui.column, state):
    uid = r['upload_id']
    status = backend.display_status(uid, r['has_tri'])
    color = STATUS_COLORS.get(status, 'grey')
    slot = backend.slot_for(uid) or '—'
    is_sel = uid in selected

    with body:
        with ui.row().classes(
                'w-full items-center gap-2 px-2 py-1.5 border-b '
                'border-grey-2 tga-row '
                + ('bg-primary-50 tga-selected cursor-default'
                   if is_sel else 'hover:bg-grey-2 cursor-pointer')) as row:
            # Checkbox button (dedicated click target — no bubbling surprises).
            # NOTE: do_select must NOT call render_rows — rebuilding the whole
            # list inside the click handler replaces the clicked button mid-
            # event, which makes rapid multi-clicks drop selections (verified
            # with playwright: 17 clicks -> 15 selected). Update only the icon.
            def do_select():
                toggle_select(uid)
                now_sel = uid in selected
                icon.set_name('check_box' if now_sel else 'check_box_outline_blank')
                icon.classes(add='text-green-600' if now_sel else 'text-grey-5 tga-sub',
                             remove='text-grey-5 tga-sub' if now_sel else 'text-green-600')
                # add/remove only — replace= would wipe the row's layout
                # classes (w-full, gap-2, tga-row) and break clicks (verified
                # with playwright stress test: 17 clicks -> 10 selected).
                row.classes(add=('bg-primary-50 tga-selected cursor-default'
                                 if now_sel else 'hover:bg-grey-2 cursor-pointer'),
                            remove=('hover:bg-grey-2 cursor-pointer'
                                    if now_sel else 'bg-primary-50 tga-selected cursor-default'))
                if on_selection_change:
                    on_selection_change()
            with ui.button('') \
                    .on('click.stop', do_select) \
                    .props('flat round dense padding=xs'):
                with ui.icon('check_box' if is_sel else 'check_box_outline_blank') \
                        .classes('text-green-600' if is_sel else 'text-grey-5 tga-sub') as icon:
                    pass
            ui.label(r['sample'] or r['name']).classes(
                'flex-1 text-sm truncate tga-title')
            ui.label(r['procedure'] or '—').classes(
                'flex-1 text-sm truncate text-grey-6 tga-sub')
            ui.label(r['author']).classes('w-32 text-sm truncate text-grey-6 tga-sub')
            ui.badge(i18n(backend.config, status)).props(f'color={color} outline').classes('w-32 text-xs')
            ui.label(slot).classes('w-12 text-sm text-center tga-title')
            ui.icon('description', color='green' if r['has_tprc'] else 'grey-4').classes('w-10 text-sm')
            ui.icon('task_alt', color='green' if r['has_tri'] else 'grey-4').classes('w-10 text-sm')
            ui.label(r['created']).classes('w-20 text-xs text-grey-6 tga-sub')
