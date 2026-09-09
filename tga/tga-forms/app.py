"""TGA Messauftrag — einfaches Formular hinter dem NOMAD-Login.

Läuft unter /nomad-oasis/tga-forms/ (gleicher Cookie-Pfad wie die NOMAD-GUI),
erbt dadurch die NOMAD-Session ('Authorization'-Cookie) und erzeugt echte
TgaMeasurement-Entries (Upload + process_now → .tprc) über die interne API.
"""
import os
import re
import uuid

from nicegui import app, ui
from starlette.requests import Request

import nomad_api


TITLE = 'TGA Messauftrag'

SEGMENT_TYPES = [
    {'id': 'ramp', 'label': 'Rampe (Aufheizen/Abkühlen)', 'fields': ['end_temp', 'rate']},
    {'id': 'isothermal', 'label': 'Isotherm (Halten)', 'fields': ['duration_min']},
    {'id': 'mass_flow', 'label': 'Gasfluss (Probe)', 'fields': ['flow_rate']},
    {'id': 'balance_flow', 'label': 'Gasfluss (Waage)', 'fields': ['flow_rate']},
]
SEG_LABEL = {s['id']: s['label'] for s in SEGMENT_TYPES}
CRUCIBLES = ['Alumina', 'Platinum', 'Aluminum']
GASES = ['N2', 'Air', 'Ar', 'Synthetic Air', 'O2']

# session store for the auth token (set on page load from the cookie)


def auth_token() -> str:
    return app.storage.client.get('auth', '')


def current_user() -> dict | None:
    tok = auth_token()
    return nomad_api.user_from_token(tok) if tok else None


# ── Formular-Zustand ─────────────────────────────────────────────────────────
form = {
    'sample_name': '',
    'sample_mass': None,
    'operator': '',
    'crucible_type': 'Alumina',
    'pan_number': '',
    'gas_atmosphere': 'N2',
    'gas_flow_rate': None,
    'balance_flow_rate': None,
    'procedure_name': 'TGA Analyse',
    'comments': '',
}
segments: list[dict] = []   # {type, end_temp, rate, duration_min, flow_rate}


# ── Segment-Karten ───────────────────────────────────────────────────────────
def segment_card(idx: int) -> ui.element:
    seg = segments[idx]
    card = ui.card().classes('w-full gap-1 p-3 bg-grey-1')
    with card:
        with ui.row().classes('w-full items-center gap-2'):
            ui.label(f'Segment {idx + 1}').classes('font-bold text-sm')
            ui.space()
            btn_up = ui.button(icon='arrow_upward', on_click=lambda i=idx: move_segment(i, -1)) \
                .props('flat round dense size=sm')
            btn_dn = ui.button(icon='arrow_downward', on_click=lambda i=idx: move_segment(i, +1)) \
                .props('flat round dense size=sm')
            ui.button(icon='delete', on_click=lambda i=idx: remove_segment(i)) \
                .props('flat round dense size=sm color=red').tooltip('Segment entfernen')
        ui.select(
            {s['id']: s['label'] for s in SEGMENT_TYPES},
            value=seg['type'],
            label='Art des Segments',
            on_change=lambda e, i=idx: set_segment_type(i, e.value),
        ).props('outlined dense').classes('w-full')
        # Felder (alle angelegt, je Typ sichtbar)
        row = ui.row().classes('w-full gap-3 items-center')
        with row:
            inp_end = ui.number('Zieltemperatur [°C]', value=seg.get('end_temp'),
                                on_change=lambda e, i=idx: set_field(i, 'end_temp', e.value)) \
                .props('outlined dense').classes('min-w-40')
            inp_rate = ui.number('Rate [°C/min]', value=seg.get('rate'),
                                 on_change=lambda e, i=idx: set_field(i, 'rate', e.value)) \
                .props('outlined dense').classes('min-w-40')
            inp_dur = ui.number('Dauer [min]', value=seg.get('duration_min'),
                                on_change=lambda e, i=idx: set_field(i, 'duration_min', e.value)) \
                .props('outlined dense').classes('min-w-40')
            inp_flow = ui.number('Gasfluss [mL/min]', value=seg.get('flow_rate'),
                                 on_change=lambda e, i=idx: set_field(i, 'flow_rate', e.value)) \
                .props('outlined dense').classes('min-w-40')
        seg['_ui'] = {'end_temp': inp_end, 'rate': inp_rate,
                      'duration_min': inp_dur, 'flow_rate': inp_flow}
        apply_segment_visibility(idx)
    return card


def apply_segment_visibility(idx: int):
    seg = segments[idx]
    ui_refs = seg.get('_ui', {})
    if seg['type'] == 'ramp':
        vis = {'end_temp': True, 'rate': True, 'duration_min': False, 'flow_rate': False}
    elif seg['type'] == 'isothermal':
        vis = {'end_temp': False, 'rate': False, 'duration_min': True, 'flow_rate': False}
    else:
        vis = {'end_temp': False, 'rate': False, 'duration_min': False, 'flow_rate': True}
    for k, ref in ui_refs.items():
        ref.set_visibility(vis[k])


def set_segment_type(idx: int, seg_type: str):
    segments[idx]['type'] = seg_type
    apply_segment_visibility(idx)


def set_field(idx: int, key: str, value):
    if value in (None, ''):
        segments[idx][key] = None
    else:
        segments[idx][key] = float(value)


def move_segment(idx: int, delta: int):
    j = idx + delta
    if 0 <= j < len(segments):
        segments[idx], segments[j] = segments[j], segments[idx]
        rebuild_segments()


def remove_segment(idx: int):
    del segments[idx]
    rebuild_segments()


# ── Segmente neu zeichnen (Container wird geleert) ───────────────────────────
seg_container = None


def rebuild_segments():
    if seg_container is None:
        return
    seg_container.clear()
    with seg_container:
        if not segments:
            ui.label('Noch keine Segmente — füge mindestens eines hinzu.')\
                .classes('text-grey-5 italic text-sm')
        for i in range(len(segments)):
            segment_card(i)


def add_segment(seg_type: str = 'ramp'):
    segments.append({'type': seg_type, 'end_temp': None, 'rate': None,
                     'duration_min': None, 'flow_rate': None})
    rebuild_segments()


# ── Submit ───────────────────────────────────────────────────────────────────
def validate() -> list[str]:
    errs = []
    if not form['sample_name'].strip():
        errs.append('Bitte einen Probennamen angeben.')
    if not segments:
        errs.append('Mindestens ein Temperatur-Segment ist nötig.')
    for i, seg in enumerate(segments):
        t = seg['type']
        if t == 'ramp' and (seg.get('end_temp') is None or seg.get('rate') is None):
            errs.append(f'Segment {i + 1}: Zieltemperatur und Rate angeben.')
        elif t == 'isothermal' and seg.get('duration_min') is None:
            errs.append(f'Segment {i + 1}: Dauer angeben.')
        elif t in ('mass_flow', 'balance_flow') and seg.get('flow_rate') is None:
            errs.append(f'Segment {i + 1}: Gasfluss angeben.')
    return errs


def collect_form() -> dict:
    f = dict(form)
    f['segments'] = [dict(s) for s in segments]
    return f


def submit():
    errs = validate()
    if errs:
        for e in errs:
            ui.notify(e, type='negative')
        return
    tok = auth_token()
    if not tok:
        ui.notify('Nicht eingeloggt — bitte zuerst in NOMAD anmelden.', type='negative')
        return
    f = collect_form()
    archive = nomad_api.build_archive(f)
    safe = re.sub(r'[^A-Za-z0-9._-]+', '_', form['sample_name'].strip())[:60]
    uniq = uuid.uuid4().hex[:8]
    upload_name = f'{safe}_{uniq}.archive.json'
    btn_submit.disable()
    ui.notify('Lege Messauftrag an …', type='info')
    try:
        st, body = nomad_api.create_tga_upload(tok, archive, upload_name)
        if st not in (200, 201):
            ui.notify(f'Fehler beim Anlegen (HTTP {st})', type='negative')
            btn_submit.enable()
            return
        # kurz warten und Upload-Status prüfen (prozess läuft async)
        import time
        time.sleep(4)
        uid = nomad_api.find_newest_upload(tok, safe)
        if uid:
            ui.notify(f'Messauftrag angelegt (Upload {uid[:8]}) — der Operator '
                      'sieht ihn jetzt in der EXE.', type='positive', timeout=8000)
            status = nomad_api.upload_state(tok, uid)
            ps = status.get('process_status', '')
            with result_box:
                result_box.clear()
                with result_box:
                    ui.icon('check_circle', color='green').classes('text-4xl')
                    ui.label('Messauftrag erfolgreich angelegt!').classes('text-lg font-bold')
                    ui.label(f'Probe: {form["sample_name"].strip()}').classes('text-sm')
                    ui.label(f'Upload-ID: {uid}').classes('text-xs text-grey-6')
                    if ps:
                        ui.label(f'Status: {ps}').classes('text-xs text-grey-6')
        else:
            ui.notify('Upload angelegt, aber noch nicht in der Liste gefunden — '
                      'bitte gleich in der EXE prüfen.', type='warning')
    except Exception as e:
        ui.notify(f'Fehler: {e}', type='negative')
    finally:
        btn_submit.enable()


# ── Seiten ───────────────────────────────────────────────────────────────────
@ui.page('/')
def index(request: 'Request'):
    cookie = request.cookies.get('Authorization', '')
    if cookie:
        app.storage.client['auth'] = cookie
    else:
        app.storage.client.pop('auth', None)
    user = current_user()

    ui.colors(primary='#4f46e5')
    # Kopf
    with ui.header().classes('items-center px-4'):
        ui.label(TITLE).classes('text-lg font-bold')
        ui.space()
        if user:
            ui.icon('account_circle')
            ui.label(str(user.get('name') or '?'))
            ui.button('NOMAD öffnen', on_click=lambda: ui.navigate.to(
                '/nomad-oasis/gui', new_tab=False)).props('flat dense')
        else:
            ui.badge('Nicht eingeloggt').props('color=orange')
            ui.button('In NOMAD einloggen (neuer Tab)', on_click=lambda: ui.navigate.to(
                '/nomad-oasis/gui', new_tab=True)).props('outline dense')

    if not user:
        with ui.column().classes('items-center w-full py-20 gap-4'):
            ui.icon('lock', color='grey').classes('text-6xl')
            ui.label('Bitte zuerst in NOMAD anmelden.').classes('text-xl')
            ui.label('Der Login öffnet sich in einem neuen Tab — sobald du angemeldet '
                     'bist, lädt diese Seite automatisch neu.') \
                .classes('text-grey-6')
            ui.button('Zum NOMAD-Login', on_click=lambda: ui.navigate.to(
                '/nomad-oasis/gui', new_tab=True)) \
                .props('unelevated')
        # Auto-Reload, sobald das Authorization-Cookie (NOMAD-Login) da ist.
        # Das Cookie (Path=/nomad-oasis/api) ist für diese Seite sichtbar, weil
        # /nomad-oasis/api/tga-forms/ darunter liegt.
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

    # Formular
    with ui.column().classes('w-full max-w-4xl mx-auto gap-4 px-4 py-6'):
        ui.label(f'Neuer TGA-Messauftrag für {user.get("name")}') \
            .classes('text-xl font-bold')
        ui.label('Der Auftrag wird als NOMAD-Eintrag angelegt; der Operator führt '
                 'ihn am Gerät aus und die EXE lädt das Ergebnis automatisch zurück.') \
            .classes('text-grey-6')

        # Probe
        with ui.card().classes('w-full gap-2 p-4'):
            ui.label('Probe').classes('font-bold')
            with ui.row().classes('w-full gap-4'):
                with ui.column().classes('gap-1 flex-1'):
                    ui.label('Probenname *')
                    ui.input(value=form['sample_name'],
                             on_change=lambda e: form.update(sample_name=e.value)) \
                        .props('outlined dense').classes('w-full')
                with ui.column().classes('gap-1 w-40'):
                    ui.label('Einwaage [mg]')
                    ui.number(value=form['sample_mass'],
                              on_change=lambda e: form.update(
                                  sample_mass=e.value if e.value not in (None, '') else None)) \
                        .props('outlined dense').classes('w-full')
            with ui.row().classes('w-full gap-4'):
                with ui.column().classes('gap-1 flex-1'):
                    ui.label('Operator')
                    ui.input(value=form['operator'],
                             on_change=lambda e: form.update(operator=e.value)) \
                        .props('outlined dense').classes('w-full')
                with ui.column().classes('gap-1 w-40'):
                    ui.label('Tiegel')
                    ui.select(CRUCIBLES, value=form['crucible_type'],
                              on_change=lambda e: form.update(crucible_type=e.value)) \
                        .props('outlined dense').classes('w-full')
                with ui.column().classes('gap-1 w-40'):
                    ui.label('Tiegel-Nr.')
                    ui.input(value=form['pan_number'],
                             on_change=lambda e: form.update(pan_number=e.value)) \
                        .props('outlined dense').classes('w-full')

        # Atmosphäre
        with ui.card().classes('w-full gap-2 p-4'):
            ui.label('Atmosphäre & Gase').classes('font-bold')
            with ui.row().classes('w-full gap-4'):
                with ui.column().classes('gap-1 w-44'):
                    ui.label('Spülgas')
                    ui.select(GASES, value=form['gas_atmosphere'],
                              on_change=lambda e: form.update(gas_atmosphere=e.value)) \
                        .props('outlined dense').classes('w-full')
                with ui.column().classes('gap-1 w-40'):
                    ui.label('Gasfluss Probe [mL/min]')
                    ui.number(value=form['gas_flow_rate'],
                              on_change=lambda e: form.update(
                                  gas_flow_rate=e.value if e.value not in (None, '') else None)) \
                        .props('outlined dense').classes('w-full')
                with ui.column().classes('gap-1 w-40'):
                    ui.label('Gasfluss Waage [mL/min]')
                    ui.number(value=form['balance_flow_rate'],
                              on_change=lambda e: form.update(
                                  balance_flow_rate=e.value if e.value not in (None, '') else None)) \
                        .props('outlined dense').classes('w-full')

        # Temperaturprogramm
        with ui.card().classes('w-full gap-2 p-4'):
            ui.label('Temperaturprogramm (Segmente in Reihenfolge)').classes('font-bold')
            global seg_container
            seg_container = ui.column().classes('w-full gap-2')
            with seg_container:
                pass
            ui.button('+ Segment hinzufügen', icon='add',
                      on_click=lambda: add_segment('ramp')) \
                .props('outline dense').classes('self-start')
        add_segment('ramp')  # Start mit einer Rampe

        # Methode & Kommentar
        with ui.card().classes('w-full gap-2 p-4'):
            ui.label('Methode & Notizen').classes('font-bold')
            with ui.column().classes('gap-1 w-full'):
                ui.label('Methodenname')
                ui.input(value=form['procedure_name'],
                         on_change=lambda e: form.update(procedure_name=e.value)) \
                    .props('outlined dense').classes('w-full')
            with ui.column().classes('gap-1 w-full'):
                ui.label('Kommentar (optional)')
                ui.textarea(value=form['comments'],
                            on_change=lambda e: form.update(comments=e.value)) \
                    .props('outlined dense autogrow').classes('w-full')

        # Absenden
        global btn_submit, result_box
        with ui.row().classes('w-full items-center gap-4 py-2'):
            btn_submit = ui.button('Messauftrag anlegen', icon='send',
                                   on_click=submit).props('unelevated size=lg')
        result_box = ui.column().classes('w-full items-center gap-1 py-4')


ui.run(host='0.0.0.0', port=int(os.environ.get('PORT', '8090')),
       title=TITLE,
       storage_secret=os.environ.get('STORAGE_SECRET', uuid.uuid4().hex),
       reload=False, show=False, language='de')
