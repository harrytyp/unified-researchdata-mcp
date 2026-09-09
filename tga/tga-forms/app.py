"""TGA Measurement Request — a guided form hosted under the NOMAD login.

Lives under /nomad-oasis/api/tga-forms/ (cookie path of the NOMAD GUI), so it
inherits the NOMAD session via the 'Authorization' cookie and creates real
TgaMeasurement entries (upload + process_now -> .tprc) through the internal API.

Design: Linear-inspired (Inter, indigo accent, luminance surfaces), English,
dark/light toggle persisted per browser session.
"""
import os
import re
import uuid

from nicegui import app, ui
from starlette.requests import Request

import nomad_api
from style_css import CSS

TITLE = 'TGA Measurement Request'
ACCENT = '#5e6ad2'

SEGMENT_TYPES = [
    {'id': 'ramp', 'label': 'Ramp (heat / cool)'},
    {'id': 'isothermal', 'label': 'Isothermal (hold)'},
    {'id': 'mass_flow', 'label': 'Gas flow (sample)'},
    {'id': 'balance_flow', 'label': 'Gas flow (balance)'},
]
SEG_LABEL = {s['id']: s['label'] for s in SEGMENT_TYPES}
CRUCIBLES = ['Alumina', 'Platinum', 'Aluminum']
GASES = ['N2', 'Air', 'Ar', 'Synthetic Air', 'O2']


# ── Per-session state (multi-user safe) ─────────────────────────────────────
def st() -> dict:
    return app.storage.client


def default_form() -> dict:
    return {
        'sample_name': '', 'sample_mass': None, 'operator': '',
        'crucible_type': 'Alumina', 'pan_number': '',
        'gas_atmosphere': 'N2', 'gas_flow_rate': None, 'balance_flow_rate': None,
        'procedure_name': 'TGA Analysis', 'comments': '',
    }


def default_segments() -> list:
    return [{'type': 'ramp', 'end_temp': None, 'rate': None,
             'duration_min': None, 'flow_rate': None}]


def get_form() -> dict:
    s = st()
    if 'form' not in s:
        s['form'] = default_form()
    return s['form']


def get_segments() -> list:
    s = st()
    if 'segments' not in s:
        s['segments'] = default_segments()
    return s['segments']


def auth_token() -> str:
    return st().get('auth', '')


def current_user() -> dict | None:
    tok = auth_token()
    return nomad_api.user_from_token(tok) if tok else None


# ── Segment card UI ──────────────────────────────────────────────────────────
def apply_segment_visibility(seg: dict, refs: dict):
    t = seg['type']
    vis = {'ramp': {'end_temp': True, 'rate': True, 'duration_min': False, 'flow_rate': False},
           'isothermal': {'end_temp': False, 'rate': False, 'duration_min': True, 'flow_rate': False}}
    vis = vis.get(t, {'end_temp': False, 'rate': False, 'duration_min': False, 'flow_rate': True})
    for k, ref in refs.items():
        ref.set_visibility(vis[k])


def set_field(idx: int, key: str, value):
    segs = get_segments()
    if value in (None, ''):
        segs[idx][key] = None
    else:
        try:
            segs[idx][key] = float(value)
        except (TypeError, ValueError):
            segs[idx][key] = None


def set_segment_type(idx: int, seg_type: str):
    get_segments()[idx]['type'] = seg_type


def move_segment(idx: int, delta: int):
    segs = get_segments()
    j = idx + delta
    if 0 <= j < len(segs):
        segs[idx], segs[j] = segs[j], segs[idx]
        rebuild_segments()


def remove_segment(idx: int):
    del get_segments()[idx]
    rebuild_segments()


def add_segment():
    get_segments().append({'type': 'ramp', 'end_temp': None, 'rate': None,
                           'duration_min': None, 'flow_rate': None})
    rebuild_segments()


seg_container = None


def rebuild_segments():
    if seg_container is None:
        return
    seg_container.clear()
    with seg_container:
        segs = get_segments()
        if not segs:
            with ui.row().classes('items-center gap-2 text-grey-5'):
                ui.icon('info')
                ui.label('No segments yet — add at least one.')
        for i in range(len(segs)):
            segment_card(i)


def segment_card(idx: int):
    seg = get_segments()[idx]

    def on_type(e):
        set_segment_type(idx, e.value)
        # rebuild to show the right fields for the new type
        rebuild_segments()

    def on_field(key):
        return lambda e: set_field(idx, key, e.value)

    with ui.element('div').classes('tga-seg') as card:
        with ui.element('div').classes('tga-seg-head'):
            with ui.row().classes('items-center gap-2 w-full'):
                ui.icon('swap_vert' if False else 'thermostat').classes('tga-seg-icon')
                ui.label(f'Segment {idx + 1}').classes('tga-seg-title')
                ui.space()
                ui.button(icon='arrow_upward', on_click=lambda: move_segment(idx, -1)) \
                    .props('flat round dense size=sm')
                ui.button(icon='arrow_downward', on_click=lambda: move_segment(idx, +1)) \
                    .props('flat round dense size=sm')
                ui.button(icon='close', on_click=lambda: remove_segment(idx)) \
                    .props('flat round dense size=sm color=red-5').tooltip('Remove segment')
        ui.select({s['id']: s['label'] for s in SEGMENT_TYPES},
                  value=seg['type'], label='Segment type', on_change=on_type) \
            .props('outlined dense').classes('w-full')
        with ui.row().classes('w-full gap-3 items-start'):
            inp_end = ui.number('Target temperature [°C]', value=seg.get('end_temp'),
                                on_change=on_field('end_temp')).props('outlined dense').classes('min-w-44')
            inp_rate = ui.number('Rate [°C/min]', value=seg.get('rate'),
                                 on_change=on_field('rate')).props('outlined dense').classes('min-w-44')
            inp_dur = ui.number('Hold time [min]', value=seg.get('duration_min'),
                                on_change=on_field('duration_min')).props('outlined dense').classes('min-w-44')
            inp_flow = ui.number('Gas flow [mL/min]', value=seg.get('flow_rate'),
                                 on_change=on_field('flow_rate')).props('outlined dense').classes('min-w-44')
        apply_segment_visibility(seg, {'end_temp': inp_end, 'rate': inp_rate,
                                       'duration_min': inp_dur, 'flow_rate': inp_flow})


# ── Validation & submit ──────────────────────────────────────────────────────
def validate() -> list:
    errs = []
    form = get_form()
    if not form['sample_name'].strip():
        errs.append('Please enter a sample name.')
    segs = get_segments()
    if not segs:
        errs.append('At least one temperature segment is required.')
    for i, seg in enumerate(segs):
        t = seg['type']
        if t == 'ramp' and (seg.get('end_temp') is None or seg.get('rate') is None):
            errs.append(f'Segment {i + 1}: enter target temperature and rate.')
        elif t == 'isothermal' and seg.get('duration_min') is None:
            errs.append(f'Segment {i + 1}: enter the hold time.')
        elif t in ('mass_flow', 'balance_flow') and seg.get('flow_rate') is None:
            errs.append(f'Segment {i + 1}: enter the gas flow rate.')
    return errs


def submit():
    errs = validate()
    if errs:
        for e in errs:
            ui.notify(e, type='negative')
        return
    tok = auth_token()
    if not tok:
        ui.notify('Not logged in — please sign in to NOMAD first.', type='negative')
        return
    form = dict(get_form())
    archive = nomad_api.build_archive({'**form': form} | {'segments': get_segments()}) \
        if False else None
    # build_archive expects the flat form keys + segments
    payload = {k: v for k, v in form.items() if k != 'segments'}
    payload['segments'] = [dict(s) for s in get_segments()]
    archive = nomad_api.build_archive(payload)
    safe = re.sub(r'[^A-Za-z0-9._-]+', '_', form['sample_name'].strip())[:60]
    upload_name = f'{safe}_{uuid.uuid4().hex[:8]}.archive.json'
    btn_submit.disable()
    ui.notify('Creating measurement request…', type='info')
    try:
        st_code, body = nomad_api.create_tga_upload(tok, archive, upload_name)
        if st_code not in (200, 201):
            ui.notify(f'Failed to create request (HTTP {st_code})', type='negative')
            btn_submit.enable()
            return
        import time
        time.sleep(4)
        uid = nomad_api.find_newest_upload(tok, safe)
        result_box.clear()
        with result_box:
            if uid:
                status = nomad_api.upload_state(tok, uid)
                ps = status.get('process_status', '')
                with ui.element('div').classes('tga-success'):
                    ui.icon('check_circle', color='#10b981').classes('text-4xl')
                    ui.label('Measurement request created!').classes('tga-success-title')
                    ui.label(f'Sample: {form["sample_name"].strip()}').classes('text-sm')
                    ui.label(f'Upload ID: {uid}').classes('tga-mono')
                    if ps:
                        ui.label(f'Status: {ps}').classes('text-sm')
                    ui.label('The operator will see this request in the TGA app and '
                             'the result is uploaded automatically after the run.')                         .classes('text-grey-5 text-sm')
            else:
                ui.label('Request submitted — check the operator app in a moment.')                     .classes('text-grey-5')
        if uid:
            ui.notify('Measurement request created ✓', type='positive', timeout=6000)
    except Exception as e:
        ui.notify(f'Error: {e}', type='negative')
    finally:
        btn_submit.enable()


# ── Global UI refs ───────────────────────────────────────────────────────────
btn_submit = None
result_box = None


# ── Dark mode (element created per page build — never cache across clients) ──


# ── Page ─────────────────────────────────────────────────────────────────────
@ui.page('/')
def index(request: Request):
    ui.add_head_html(CSS)
    cookie = request.cookies.get('Authorization', '')
    if cookie:
        st()['auth'] = cookie
    else:
        st().pop('auth', None)
    user = current_user()

    dm = ui.dark_mode(value=st().get('dark', True))

    def toggle_dark():
        new = not dm.value
        dm.value = new
        st()['dark'] = new

    ui.colors(primary=ACCENT)

    # Header
    with ui.header().classes('tga-header items-center px-4 gap-3 no-shadow') as header:
        with ui.row().classes('items-center gap-2'):
            ui.icon('whatshot', color=ACCENT).classes('text-2xl')
            ui.label(TITLE).classes('tga-brand')
        ui.space()
        if user:
            ui.icon('account_circle').classes('text-grey-4')
            ui.label(str(user.get('name') or '?')).classes('tga-user')
            ui.button('NOMAD', on_click=lambda: ui.navigate.to('/nomad-oasis/gui', new_tab=True)) \
                .props('flat dense outline').classes('tga-header-btn')
        else:
            ui.badge('Not signed in').props('color=amber-8')
            ui.button('Sign in', on_click=lambda: ui.navigate.to(
                '/nomad-oasis/gui', new_tab=True)).props('outline dense')
        ui.button(icon='dark_mode', on_click=toggle_dark).props('flat round dense') \
            .tooltip('Toggle dark / light mode').classes('tga-darkbtn')

    # ── Not signed in ──
    if not user:
        with ui.column().classes('tga-login-wrap items-center'):
            with ui.element('div').classes('tga-login-card'):
                ui.icon('lock', color=ACCENT).classes('text-5xl')
                ui.label('Signed in to NOMAD required').classes('tga-login-title')
                ui.label('This form uses your NOMAD account. The sign-in opens in a '
                         'new tab — this page reloads automatically once you are '
                         'signed in.').classes('tga-login-sub')
                ui.button('Sign in to NOMAD', icon='login', on_click=lambda: ui.navigate.to(
                    '/nomad-oasis/gui', new_tab=True)).props('unelevated size=lg').classes('tga-cta')
        ui.add_body_html('''
            <script>
            if (!document.cookie.includes('Authorization=')) {
                (function pollAuth() {
                    if (document.cookie.includes('Authorization=')) {
                        location.reload();
                    } else {
                        setTimeout(pollAuth, 1500);
                    }
                })();
            }
            </script>
        ''')
        return

    # ── Form ──
    with ui.column().classes('w-full tga-page'):
        with ui.column().classes('w-full tga-hero'):
            ui.label(f'New measurement request').classes('tga-hero-title')
            ui.label('Fill in the sample and the temperature program — the request is '
                     'created as a NOMAD entry and executed by the TGA operator.') \
                .classes('tga-hero-sub')


        # 1 — Sample
        with ui.element('div').classes('tga-panel'):
            with ui.row().classes('items-start gap-3 w-full'):
                ui.icon('science', color=ACCENT).classes('tga-section-icon')
                with ui.column().classes('gap-0'):
                    ui.label('1 · Sample').classes('tga-section-title')
                    ui.label('Who and what is being measured.').classes('tga-section-sub')
            with ui.row().classes('w-full gap-4 mt-1'):
                with ui.column().classes('gap-1 flex-1'):
                    ui.label('Sample name *').classes('tga-label')
                    ui.input(value=get_form()['sample_name'],
                             on_change=lambda e: get_form().update(sample_name=e.value)) \
                        .props('outlined dense').classes('w-full')
                with ui.column().classes('gap-1 w-44'):
                    ui.label('Mass [mg]').classes('tga-label')
                    ui.number(value=get_form()['sample_mass'],
                              on_change=lambda e: get_form().update(
                                  sample_mass=e.value if e.value not in (None, '') else None)) \
                        .props('outlined dense').classes('w-full')
            with ui.row().classes('w-full gap-4 mt-2'):
                with ui.column().classes('gap-1 flex-1'):
                    ui.label('Operator').classes('tga-label')
                    ui.input(value=get_form()['operator'],
                             on_change=lambda e: get_form().update(operator=e.value)) \
                        .props('outlined dense').classes('w-full')
                with ui.column().classes('gap-1 w-44'):
                    ui.label('Crucible').classes('tga-label')
                    ui.select(CRUCIBLES, value=get_form()['crucible_type'],
                              on_change=lambda e: get_form().update(crucible_type=e.value)) \
                        .props('outlined dense').classes('w-full')
                with ui.column().classes('gap-1 w-44'):
                    ui.label('Crucible no.').classes('tga-label')
                    ui.input(value=get_form()['pan_number'],
                             on_change=lambda e: get_form().update(pan_number=e.value)) \
                        .props('outlined dense').classes('w-full')

        # 2 — Atmosphere
        with ui.element('div').classes('tga-panel'):
            with ui.row().classes('items-start gap-3 w-full'):
                ui.icon('air', color=ACCENT).classes('tga-section-icon')
                with ui.column().classes('gap-0'):
                    ui.label('2 · Atmosphere & gases').classes('tga-section-title')
                    ui.label('Purge gas and flow rates.').classes('tga-section-sub')
            with ui.row().classes('w-full gap-4 mt-1'):
                with ui.column().classes('gap-1 w-48'):
                    ui.label('Purge gas').classes('tga-label')
                    ui.select(GASES, value=get_form()['gas_atmosphere'],
                              on_change=lambda e: get_form().update(gas_atmosphere=e.value)) \
                        .props('outlined dense').classes('w-full')
                with ui.column().classes('gap-1 w-44'):
                    ui.label('Sample flow [mL/min]').classes('tga-label')
                    ui.number(value=get_form()['gas_flow_rate'],
                              on_change=lambda e: get_form().update(
                                  gas_flow_rate=e.value if e.value not in (None, '') else None)) \
                        .props('outlined dense').classes('w-full')
                with ui.column().classes('gap-1 w-44'):
                    ui.label('Balance flow [mL/min]').classes('tga-label')
                    ui.number(value=get_form()['balance_flow_rate'],
                              on_change=lambda e: get_form().update(
                                  balance_flow_rate=e.value if e.value not in (None, '') else None)) \
                        .props('outlined dense').classes('w-full')

        # 3 — Temperature program
        with ui.element('div').classes('tga-panel'):
            with ui.row().classes('items-start gap-3 w-full'):
                ui.icon('show_chart', color=ACCENT).classes('tga-section-icon')
                with ui.column().classes('gap-0 flex-1'):
                    ui.label('3 · Temperature program').classes('tga-section-title')
                    ui.label('Segments run in order — add as many as you need '
                             '(ramps, holds, gas steps).').classes('tga-section-sub')
            global seg_container
            seg_container = ui.column().classes('w-full gap-3 mt-1')
            rebuild_segments()
            ui.button('+ Add segment', icon='add', on_click=add_segment) \
                .props('outline dense').classes('self-start tga-addseg')

        # 4 — Method & notes
        with ui.element('div').classes('tga-panel'):
            with ui.row().classes('items-start gap-3 w-full'):
                ui.icon('edit_note', color=ACCENT).classes('tga-section-icon')
                with ui.column().classes('gap-0 flex-1'):
                    ui.label('4 · Method & notes').classes('tga-section-title')
                    ui.label('Optional details for the operator.').classes('tga-section-sub')
            with ui.column().classes('gap-1 w-full mt-1'):
                ui.label('Method name').classes('tga-label')
                ui.input(value=get_form()['procedure_name'],
                         on_change=lambda e: get_form().update(procedure_name=e.value)) \
                    .props('outlined dense').classes('w-full')
            with ui.column().classes('gap-1 w-full mt-2'):
                ui.label('Comments (optional)').classes('tga-label')
                ui.textarea(value=get_form()['comments'],
                            on_change=lambda e: get_form().update(comments=e.value)) \
                    .props('outlined dense autogrow').classes('w-full')

        # Submit
        with ui.row().classes('w-full items-center gap-4 py-4'):
            global btn_submit
            btn_submit = ui.button('Create measurement request', icon='send',
                                   on_click=submit).props('unelevated size=lg').classes('tga-cta')
        global result_box
        result_box = ui.column().classes('w-full items-center gap-2')


ui.run(host='0.0.0.0', port=int(os.environ.get('PORT', '8090')),
       title=TITLE, storage_secret=os.environ.get('STORAGE_SECRET', uuid.uuid4().hex),
       reload=False, show=False, language='en')
