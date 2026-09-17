"""TGA Measurement Request: a guided form hosted under the NOMAD login.

Lives under /nomad-oasis/api/tga-forms/ (cookie path of the NOMAD GUI), so it
inherits the NOMAD session via the 'Authorization' cookie and creates real
TgaMeasurement entries (upload + process_now -> .tprc) through the internal API.

Design: Linear-inspired (Inter, indigo accent, luminance surfaces), English,
dark/light toggle persisted per browser session.
"""
import os
import re
import urllib.parse
import uuid

from nicegui import app, ui
from starlette.requests import Request

from session_email import email_from_token

import nomad_api
import ui_notify
from notify import settings as settings_mod
from style_css import CSS

TITLE = 'TGA Measurement Request'
ACCENT = '#5e6ad2'

SEGMENT_TYPES = [
    # Only the temperature program is the requester's to define. Gas flow steps
    # are part of the lab's instrument setup and are not offered here.
    {'id': 'ramp', 'label': 'Ramp (heat / cool)'},
    {'id': 'isothermal', 'label': 'Isothermal (hold)'},
]
SEG_LABEL = {s['id']: s['label'] for s in SEGMENT_TYPES}
OPEN_LOGIN_JS = '(e) => { try { window.__tgaLogin = window.open("/nomad-oasis/gui", "_blank"); } catch (err) { window.location = "/nomad-oasis/gui"; } }'

# Wait until the Authorization cookie appears, then close the login window and
# reload this page (the page was built before the sign-in, so it has to be
# rebuilt with the session in place).
AUTH_POLL_JS = '''
    <script>
    (function pollAuth() {
        if (document.cookie.includes('Authorization=')) {
            try { if (window.__tgaLogin && !window.__tgaLogin.closed) window.__tgaLogin.close(); } catch (err) {}
            location.reload();
        } else {
            setTimeout(pollAuth, 1000);
        }
    })();
    </script>
'''

# Same idea for a session that ran out of time: here the (expired) cookie is
# still present, so waiting for it to appear would reload in a loop. Wait for a
# *new* value instead - signing in again replaces the cookie.
AUTH_REFRESH_JS = '''
    <script>
    (function () {
        var find = function () {
            return (document.cookie.split('; ').find(function (c) {
                return c.indexOf('Authorization=') === 0;
            }) || '');
        };
        var start = find();
        (function pollAuth() {
            var now = find();
            if (now && now !== start) {
                try { if (window.__tgaLogin && !window.__tgaLogin.closed) window.__tgaLogin.close(); } catch (err) {}
                location.reload();
            } else {
                setTimeout(pollAuth, 1000);
            }
        })();
    })();
    </script>
'''


# The purge gas flows are part of the instrument setup the lab specifies: they
# are the same for every measurement, and a wrong value would silently change
# the atmosphere. The form therefore shows them as information instead of
# offering input, and build_archive writes the lab's values.
LAB_SAMPLE_FLOW = 20.0      # mL/min sample purge gas
LAB_BALANCE_FLOW = 10.0     # mL/min balance purge gas
LAB_FLOW_UNIT = 'mL/min'

# Crucibles the lab uses. No aluminium: those pans react with our samples and
# would change the result, so the form does not offer them at all.
CRUCIBLES = ['Alumina', 'Platinum']
# The lab's sample rules. Only nitrogen and air are set up; every other
# atmosphere needs a consultation, so the form does not offer them.
GASES = ['N2', 'Air']

# ── Sample rules (the "Sample requirements" panel shows these to the user) ──
PAN_MAX_MM = 5            # the sample has to fit the pan: max 5 x 5 mm
MASS_MAX_MG = 100.0       # hard upper limit for the weighed sample
MASS_OPT_MG = 50.0        # weight the lab aims for
RUNTIME_CONSULT_H = 24    # runs longer than a day have to be agreed first
PEDRO = 'p.braun@tum.de'
LUCA = 'luca.reichert@tum.de'
CONTACTS = f'Pedro Braun ({PEDRO}) or Luca Reichert ({LUCA})'
# Where the samples go - the requester only learns this together with the
# sample ID, so it is shown in the confirmation and nowhere else.
LAB_ADDRESS = (
    'TUM School of Engineering and Design',
    'Department of Materials Engineering',
    'Lehrstuhl für Werkstoffwissenschaften',
    'Boltzmannstr. 15',
    '85748 Garching',
    'Room MW 2228',
)
# Unit options per quantity: exactly the units NOMAD's unit system accepts for
# these quantities. The user enters the value in whichever of these they think
# in; nomad_api.build_archive converts it into the schema's canonical unit, so
# the NOMAD entry and the generated .tprc always carry canonical units.
UNIT_MASS = ['mg']  # the field takes mg only - no unit switching for mass
UNIT_TEMP = ['°C', 'K']
UNIT_RATE = ['°C/min', 'K/min']
UNIT_TIME = ['min', 's', 'h']
UNIT_FLOW = ['mL/min', 'L/min']

# TGA operator group in NOMAD. It is written into every request as a co-author:
# the submitting user stays the owner (and keeps seeing the upload in the GUI),
# while any operator account can see the request and put the result into it.
OPERATOR_GROUP = 'tga-operators-6a7ae5e4cec5e87bf39df8a3'
# NOMAD GUI base, for the deep link to a created upload.
GUI_BASE = 'https://researchmcp.duckdns.org/nomad-oasis/gui'

# Short sample id handed to the requester on submit. It is the first
# characters of the NOMAD upload_id, so the same code appears on the operator's
# board card and can be matched back to the full upload id in NOMAD.
# Written on the sample by hand, so keep it short enough to write.
SAMPLE_ID_LEN = 5


# ── Per-session state (multi-user safe) ─────────────────────────────────────
def st() -> dict:
    return app.storage.client


def default_form() -> dict:
    return {
        'sample_name': '', 'sample_mass': None,
        'crucible_type': 'Alumina',
        # The flows belong to the lab, so they are prefilled and not editable
        # (see LAB_SAMPLE_FLOW). The crucible slot is assigned by the operators,
        # not by the requester, so the form carries no pan number.
        'gas_atmosphere': 'N2',
        'gas_flow_rate': LAB_SAMPLE_FLOW, 'balance_flow_rate': LAB_BALANCE_FLOW,
        # procedure_name is left empty on purpose: it is suggested from the
        # segments (see update_method_suggestion) unless the user edits it.
        'procedure_name': '', 'last_suggestion': '', 'comments': '',
        # units the user enters values in (converted to canonical on submit)
        'mass_unit': 'mg', 'temp_unit': '°C', 'rate_unit': '°C/min',
        'time_unit': 'min', 'flow_unit': LAB_FLOW_UNIT,
        # Sample rules: one statement that the sample fulfils them (what the
        # software cannot check), plus the metallic flag that switches the
        # crucible rule and the consultation.
        'rules_ack': False,
        'metallic': False, 'ms_coupling': False, 'consulted': False,
        # where the result should go - prefilled from the NOMAD session
        'requester_email': '',
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


async def fresh_token() -> str:
    """The token to submit with - read from the browser, not from page load.

    st()['auth'] is frozen while the page is built. The page then stays open
    while the form is filled in, and NOMAD's GUI keeps refreshing the
    Authorization cookie in the browser - but this websocket connection still
    carries the cookie from page load. Submitting with that frozen value ends
    in 'HTTP 401 ... Expired token.' once it has aged out (reproduced with a
    60 s token: form loaded fine, submit failed), so ask the browser for the
    cookie it holds right now and fall back to the stored one.
    """
    raw = ''
    try:
        raw = await ui.run_javascript(
            'document.cookie.split("; ")'
            '.find(c => c.startsWith("Authorization="))'
            '?.substring("Authorization=".length) || ""', timeout=5)
    except Exception:
        raw = ''
    tok = urllib.parse.unquote(str(raw or '')).strip()
    if tok:
        st()['auth'] = tok
        return tok
    return auth_token()


def current_user() -> dict | None:
    tok = auth_token()
    return nomad_api.user_from_token(tok) if tok else None


async def prefill_session_fields():
    """Fill in what the session already knows - the requester can override it.

    Whether this finds an address depends on the login token: NOMAD's realm
    hands out a claim only if the Keycloak client includes the email scope. If
    it does not, the field simply stays empty for the requester to fill in.
    """
    try:
        tok = await fresh_token()
    except Exception:
        return
    email = email_from_token(tok)
    if not email:
        return
    form = get_form()
    if (form.get('requester_email') or '').strip():
        return  # the user typed one already, do not overwrite it
    form['requester_email'] = email
    field = unit_refs.get('requester_email')
    if field is not None:
        try:
            field.value = email
        except Exception:
            pass


# ── Segment card UI ──────────────────────────────────────────────────────────
def apply_segment_visibility(seg: dict, refs: dict):
    t = seg['type']
    vis = {'ramp': {'end_temp': True, 'rate': True, 'duration_min': False, 'flow_rate': False},
           'isothermal': {'end_temp': False, 'rate': False, 'duration_min': True, 'flow_rate': False}}
    # Unknown/legacy types keep the flow field visible: the type list no longer
    # offers gas flow steps, but an old session may still carry one.
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
    # the method name is derived from the segments, so it has to follow every
    # edit of a segment value - and so do the run time estimate and the
    # consultation rule, which depend on the program
    update_method_suggestion()
    update_runtime_label()
    update_consult_box()


# ── Units ────────────────────────────────────────────────────────────────────
# The numbers the user sees are in the unit they picked; nomad_api.build_archive
# converts everything into the schema's canonical unit on submit. When a unit
# dropdown is changed, values already entered are converted so the physical
# value stays the same (same behaviour as NOMAD's own ELN form).
unit_refs = {}
# Widgets that the sample rules have to reach (crucible select, consultation
# block, run-time label). Also per page build, like unit_refs.
rules_refs = {}


def _convert_value(kind: str, value, old_unit: str, new_unit: str):
    if value is None or old_unit == new_unit:
        return value
    canonical = nomad_api.to_canonical(kind, value, old_unit)
    return nomad_api.from_canonical(kind, canonical, new_unit)


def change_unit(kind: str, new_unit: str, seg_keys=None, form_keys=None):
    """Switch the unit for one quantity, keeping the physical values intact."""
    form = get_form()
    old_unit = form.get(f'{kind}_unit') or new_unit
    form[f'{kind}_unit'] = new_unit
    if old_unit == new_unit:
        return
    for key in (seg_keys or []):
        for seg in get_segments():
            seg[key] = _convert_value(kind, seg.get(key), old_unit, new_unit)
    for key in (form_keys or []):
        form[key] = _convert_value(kind, form.get(key), old_unit, new_unit)
        ref = unit_refs.get(key)
        if ref is not None:
            try:
                ref.value = form.get(key)
            except Exception:
                pass
    if seg_keys:
        rebuild_segments()
    else:
        update_method_suggestion()


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
method_input = None


def update_method_suggestion():
    """Keep the method name in sync with the segments.

    The name is patched into the .tprc (it is the procedure name the operator
    sees in TRIOS), so the segments themselves are the most useful default.
    It is only filled while the field still holds the automatic suggestion (or
    is empty) - once the user types a name of their own, theirs wins.
    """
    form = get_form()
    name = nomad_api.suggest_method_name(
        get_segments(), temp_unit=form.get('temp_unit') or '°C',
        rate_unit=form.get('rate_unit') or '°C/min',
        time_unit=form.get('time_unit') or 'min',
        flow_unit=form.get('flow_unit') or 'mL/min',
        gas=form.get('gas_atmosphere'))
    current = form.get('procedure_name') or ''
    if current and current != (form.get('last_suggestion') or ''):
        return  # the user wrote their own name - leave it alone
    form['last_suggestion'] = name
    form['procedure_name'] = name
    if method_input is not None:
        try:
            method_input.value = name
        except Exception:
            pass


def on_sample_name_change(value):
    get_form()['sample_name'] = value
    # the consultation mail prefills the sample name, so it has to follow
    update_consult_box()


def _mass_ok(value) -> bool:
    """Field rule for the sample mass: 0..100 mg, not enforced by clamping.

    Quasar's own max= would silently rewrite 150 to 100; the point is that the
    field turns red and the request cannot be sent, so the value stays as typed.
    """
    if value in (None, ''):
        return True
    try:
        return 0 <= float(value) <= MASS_MAX_MG
    except (TypeError, ValueError):
        return False


def on_mass_change(value):
    get_form()['sample_mass'] = value if value not in (None, '') else None


def update_runtime_label():
    """Show the estimated run time - the >1 day rule depends on it."""
    label = rules_refs.get('runtime')
    if label is None:
        return
    hours = estimated_runtime_h()
    if hours is None:
        label.set_text('Estimated run time: fill in the segments to see it.')
        label.classes(remove='tga-rules-warn')
        return
    text = f'Estimated run time: about {hours:.1f} h'
    if hours > RUNTIME_CONSULT_H:
        label.set_text(text + ' - longer than 1 day, needs a consultation first.')
        label.classes(add='tga-rules-warn')
    else:
        label.set_text(text + '.')
        label.classes(remove='tga-rules-warn')


def update_consult_box():
    """Render the consultation gate only when the request actually needs one.

    A metallic sample (the alumina crucible may have to be ordered), an
    MS-coupled measurement and a run above a day all have to be agreed with the
    lab first. The checkbox it contains is what validate() requires.
    """
    box = rules_refs.get('consult')
    if box is None:
        return
    reasons = consultation_reasons()
    box.clear()
    with box:
        if not reasons:
            return
        with ui.element('div').classes('tga-consult'):
            ui.icon('support_agent', color='#f59e0b').classes('text-3xl')
            ui.label('Consultation needed before this can be measured') \
                .classes('tga-rules-title')
            for reason in reasons:
                ui.label('- ' + reason).classes('tga-rules-text')
            ui.label(f'Please contact {CONTACTS} before submitting.') \
                .classes('tga-rules-text')
            ui.label('Write to them and say what has to be agreed - the sample name is '
                     'enough, the request does not exist yet. The link opens a mail with '
                     'what the form already knows.').classes('tga-rules-text')
            ui.link('Open the prefilled email to Pedro and Luca', consultation_mailto()) \
                .classes('tga-consult-link')
            ui.checkbox(f'I have contacted {CONTACTS} about this.',
                        value=bool(get_form().get('consulted')),
                        on_change=lambda e: get_form().update(consulted=bool(e.value)))


def on_metallic_change(value):
    """Metallic samples must run in an alumina crucible - enforce, don't hint."""
    get_form()['metallic'] = bool(value)
    sel = rules_refs.get('crucible')
    if sel is not None:
        if value:
            get_form()['crucible_type'] = 'Alumina'
            sel.value = 'Alumina'
            sel.disable()
        else:
            sel.enable()
        sel.update()
    update_consult_box()


def on_coupling_change(value):
    get_form()['ms_coupling'] = bool(value)
    update_consult_box()


def rebuild_segments():
    if seg_container is None:
        return
    seg_container.clear()
    with seg_container:
        segs = get_segments()
        if not segs:
            with ui.row().classes('items-center gap-2 text-grey-5'):
                ui.icon('info')
                ui.label('No segments yet. Add at least one to continue.')
        for i in range(len(segs)):
            segment_card(i)
    update_method_suggestion()
    # the run time and the consultation rule follow the segment list
    update_runtime_label()
    update_consult_box()


def segment_card(idx: int):
    seg = get_segments()[idx]

    def on_type(e):
        # A keystroke can race the page teardown (browser reload): the client
        # context is gone and rebuild_segments() would raise 'The parent
        # element this slot belongs to has been deleted.' - the reload rebuilds
        # the page anyway, so ignore the event.
        try:
            set_segment_type(idx, e.value)
            # rebuild to show the right fields for the new type
            rebuild_segments()
        except RuntimeError:
            return

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
            _f = get_form()
            inp_end = ui.number(f'Target temperature [{_f["temp_unit"]}]', value=seg.get('end_temp'),
                                on_change=on_field('end_temp')).props('outlined dense').classes('min-w-44')
            inp_rate = ui.number(f'Rate [{_f["rate_unit"]}]', value=seg.get('rate'),
                                 on_change=on_field('rate')).props('outlined dense').classes('min-w-44')
            inp_dur = ui.number(f'Hold time [{_f["time_unit"]}]', value=seg.get('duration_min'),
                                on_change=on_field('duration_min')).props('outlined dense').classes('min-w-44')
        # No gas flow field: the flow steps belong to the lab's setup, not to
        # the requester. A legacy segment that still carries a flow step simply
        # shows nothing extra here (the value is written on submit).
        apply_segment_visibility(seg, {'end_temp': inp_end, 'rate': inp_rate,
                                       'duration_min': inp_dur})


# ── Validation & submit ──────────────────────────────────────────────────────
# ── Sample rules: what the form can check by itself ─────────────────────────
def mass_in_mg() -> float | None:
    """The entered sample mass in mg, whatever unit the user picked."""
    form = get_form()
    value = form.get('sample_mass')
    if value in (None, ''):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value * 1000.0 if form.get('mass_unit') == 'g' else value


def estimated_runtime_h() -> float | None:
    """Rough run time of the entered program, in hours.

    Ramps are estimated from room temperature (25 degC) to their target at the
    entered rate, holds count in full, mass/balance flow steps add no time.
    This is an estimate: it exists so the ">1 day needs a consultation" rule is
    visible *before* submitting, not to predict the exact run.
    """
    segs = get_segments()
    if not segs:
        return None
    total_min = 0.0
    known = False
    for seg in segs:
        t = seg.get('type')
        if t == 'ramp':
            end, rate = seg.get('end_temp'), seg.get('rate')
            if end is None or not rate:
                continue
            # the rate is entered in degC/min or K/min - same step size either way
            total_min += max(0.0, (float(end) - 25.0)) / abs(float(rate))
            known = True
        elif t == 'isothermal':
            dur = seg.get('duration_min')
            if dur is not None:
                total_min += float(dur)
                known = True
    return (total_min / 60.0) if known else None


def consultation_reasons() -> list:
    """Why this request has to be agreed with the lab before it is measured."""
    form = get_form()
    reasons = []
    if form.get('metallic'):
        reasons.append('metallic sample - the alumina crucible may have to be ordered')
    if form.get('ms_coupling'):
        reasons.append('mass-spectrometer coupled measurement')
    hours = estimated_runtime_h()
    if hours is not None and hours > RUNTIME_CONSULT_H:
        reasons.append(f'run time above 1 day (estimated ~{hours:.0f} h)')
    return reasons


def consultation_mailto() -> str:
    """A prefilled mail, so 'arrange a consultation' is one click and not a guess.

    The form asks for the consultation *before* the request is sent, so there is
    no sample id yet - the mail carries the sample name and the reason instead.
    """
    form = get_form()
    sample = (form.get('sample_name') or '').strip()
    subject = 'TGA measurement - consultation needed'
    if sample:
        subject += f' - {sample}'
    reasons = '; '.join(consultation_reasons()) or 'to be agreed'
    body = (
        'Hello,\n\n'
        'I would like to register a TGA measurement and need a consultation.\n\n'
        f'Sample: {sample or "(name not set yet)"}\n'
        f'Reason: {reasons}\n'
        f'Atmosphere: {form.get("gas_atmosphere") or "N2"}\n'
        f'Estimated run time: {estimated_runtime_h() or 0:.1f} h\n\n'
        'What I want to measure:\n\n\n'
        'Best regards\n'
    )
    return ('mailto:' + urllib.parse.quote(PEDRO) + ',' + urllib.parse.quote(LUCA)
            + '?subject=' + urllib.parse.quote(subject)
            + '&body=' + urllib.parse.quote(body))


def validate() -> list:
    errs = []
    form = get_form()
    if not form['sample_name'].strip():
        errs.append('Please enter a sample name.')
    email = (form.get('requester_email') or '').strip()
    if not email:
        errs.append('Please enter the email address the result should go to.')
    elif '@' not in email or '.' not in email.split('@')[-1]:
        errs.append('That does not look like an email address.')
    # The mass limit is enforced by the field itself (it turns red and refuses
    # the value) - this is the net for anything that bypasses the field.
    mass = mass_in_mg()
    if mass is None:
        errs.append('Please enter the sample mass.')
    elif mass > MASS_MAX_MG:
        errs.append(f'Sample mass {mass:.0f} mg is above the {MASS_MAX_MG:.0f} mg limit '
                    f'(aim for {MASS_OPT_MG:.0f} mg).')
    if not form.get('rules_ack'):
        errs.append('Please confirm that your sample fulfils the sample requirements.')
    if form.get('metallic') and form.get('crucible_type') != 'Alumina':
        errs.append('Metallic samples can only be measured in an alumina crucible.')
    reasons = consultation_reasons()
    if reasons and not form.get('consulted'):
        errs.append('This request needs a consultation first (' + '; '.join(reasons)
                    + f'): please confirm that you have contacted {CONTACTS}.')
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


def create_request(tok: str, archive: dict, file_name: str, display_name: str,
                   name_prefix: str) -> dict:
    """Create the request upload and wire up operator access.

    Runs OFF the UI thread (submit() awaits it through run.io_bound): NOMAD
    takes ~10 s to process a new upload, and the follow-up metadata edit that
    adds the operator group is rejected while that processing is still running
    ("'NoneType' object has no attribute 'is_blocking'"). Blocking the NiceGUI
    event loop for that long would freeze the page for every user.

    Returns {'status', 'uid', 'error', 'group_status'}.
    """
    out = {'status': None, 'uid': None, 'error': None, 'group_status': None}
    st_code, uid, body = nomad_api.create_tga_upload(
        tok, archive, file_name, display_name)
    out['status'] = st_code
    if st_code not in (200, 201):
        out['error'] = body[:140]
        return out
    if not uid:
        import time
        time.sleep(4)
        uid = nomad_api.find_newest_upload(tok, name_prefix)
    out['uid'] = uid
    if uid and OPERATOR_GROUP:
        # add_operator_group waits for the upload to be idle first
        try:
            gst, _ = nomad_api.add_operator_group(tok, uid, OPERATOR_GROUP)
            out['group_status'] = gst
        except Exception as e:
            out['group_status'] = f'error: {e}'
    return out


def show_session_expired(detail: str = ''):
    """Explain a 401/403 as an expired session and offer the way back in.

    A 401 is not a problem with the form: the session token NOMAD was handed
    is no longer valid (it aged out while the form was being filled). Nothing
    was created and the entries are still in the form, so signing in again and
    pressing submit once more is all it takes. Without this the user only saw
    the raw API error and had no idea whether their data was lost.
    """
    result_box.clear()
    with result_box:
        with ui.element('div').classes('tga-expired'):
            ui.icon('lock_clock', color='#f59e0b').classes('text-4xl')
            ui.label('NOMAD session expired').classes('tga-success-title')
            ui.label('Your sign-in was no longer valid when the request was sent, '
                     'so nothing was created. Sign in again and press submit once '
                     'more - your entries are kept.').classes('text-sm text-grey-5')
            ui.button('Sign in to NOMAD', icon='login') \
                .on('click', js_handler=OPEN_LOGIN_JS) \
                .props('unelevated').classes('tga-cta')
            if detail:
                ui.label(detail).classes('tga-mono')
    ui.add_body_html(AUTH_REFRESH_JS)


async def submit():
    from nicegui import run
    errs = validate()
    if errs:
        for e in errs:
            ui.notify(e, type='negative')
        return
    tok = await fresh_token()
    if not tok:
        ui.notify('Not logged in. Please sign in to NOMAD first.', type='negative')
        return
    form = dict(get_form())
    user = current_user() or {}
    # build_archive expects the flat form keys + segments (and converts every
    # value from the unit the user picked into the schema's canonical unit)
    payload = {k: v for k, v in form.items()}
    payload['segments'] = [dict(s) for s in get_segments()]
    # Tell the operator what the requester declared beyond the raw fields -
    # these drive work on their side (crucible ordering, MS setup, scheduling),
    # and the operator only sees the NOMAD entry, not this form.
    notes = []
    if form.get('metallic'):
        notes.append('metallic sample - alumina crucible')
    if form.get('ms_coupling'):
        notes.append('mass-spectrometer coupled measurement requested')
    hours = estimated_runtime_h()
    if hours is not None and hours > RUNTIME_CONSULT_H:
        notes.append(f'estimated run time {hours:.1f} h')
    if notes:
        existing = (payload.get('comments') or '').strip()
        payload['comments'] = ((existing + ' | ') if existing else '') \
            + 'Request notes: ' + '; '.join(notes)
    archive = nomad_api.build_archive(payload)
    sample = form['sample_name'].strip()
    safe = re.sub(r'[^A-Za-z0-9._-]+', '_', sample)[:60] or 'TGA'
    file_name = f'{safe}_{uuid.uuid4().hex[:8]}.archive.json'
    # Human readable upload name so the request is easy to find in the GUI
    # (without it NOMAD names the upload after the .archive.json file).
    display_name = f'TGA Request: {sample}'
    if user.get('name'):
        display_name += f' ({user["name"]})'
    btn_submit.disable()
    ui.notify('Creating measurement request…', type='info')
    try:
        res = await run.io_bound(create_request, tok, archive, file_name,
                                 display_name, safe)
        if res['error']:
            if res['status'] in (401, 403):
                # not a form problem - the session is gone; explain it and
                # offer the way back instead of dumping the API error
                show_session_expired(str(res['error']))
                return
            ui.notify(f'Failed to create request (HTTP {res["status"]}): {res["error"]}',
                      type='negative')
            return
        uid = res['uid']
        if uid:
            # Operator und Auftraggeber erfahren vom Antrag. Bewusst nach dem
            # Upload (die Links in der Mail muessen funktionieren) und bewusst
            # ohne den Antrag zu gefaehrden, falls das Einreihen scheitert.
            try:
                for _report in ui_notify.notify_new_request(
                        uid, archive, user, consultation_reasons()):
                    if _report.get('status') not in ('sent', 'queued'):
                        ui.notify(f"Notification {_report.get('event')}: "
                                  f"{_report.get('status')}", type='warning')
            except Exception as _notify_error:
                ui.notify(f'Notification failed: {_notify_error}', type='warning')
        if res['group_status'] not in (200, 201) and OPERATOR_GROUP:
            ui.notify(f'Operator group not added ({res["group_status"]})', type='warning')
        result_box.clear()
        with result_box:
            if uid:
                status = nomad_api.upload_state(tok, uid)
                ps = status.get('process_status', '')
                with ui.element('div').classes('tga-success'):
                    ui.icon('check_circle', color='#10b981').classes('text-4xl')
                    ui.label('Measurement request created!').classes('tga-success-title')
                    ui.label(f'Sample: {sample}').classes('text-sm')
                    # The requester writes this code on the sample they send
                    # in; the operator sees the same code on the board card.
                    with ui.element('div').classes('tga-sampleid'):
                        ui.label('Sample ID - write this on the sample you send in') \
                            .classes('tga-sampleid-hint')
                        ui.label(uid[:SAMPLE_ID_LEN]).classes('tga-sampleid-code')
                    ui.label(f'Upload ID: {uid}').classes('tga-mono')
                    if ps:
                        ui.label(f'Status: {ps}').classes('text-sm')
                    # The requester gets the code and the drop-off address in
                    # the same place - that is the moment they need both.
                    with ui.element('div').classes('tga-dropoff-box'):
                        ui.label('Bring the sample to the lab - after agreeing the '
                                 'drop-off with Pedro or Luca by email:') \
                            .classes('tga-dropoff-lead')
                        ui.label('\n'.join(LAB_ADDRESS)).classes('tga-dropoff-addr')
                    if get_form().get('requester_email'):
                        ui.label(f'Contact address for this request: '
                                 f'{get_form()["requester_email"]}').classes('tga-hint')
                    ui.button(
                        'Open this upload in NOMAD',
                        on_click=lambda: ui.navigate.to(
                            f'{GUI_BASE}/user/uploads/upload/id/{uid}', new_tab=True)) \
                        .props('flat dense no-caps').classes('tga-nomad-link')
                    ui.label('The operator will see this request in the TGA app. '
                             'The result files and the plots are added to this same '
                             'upload after the run, so everything stays in one place '
                             'and remains visible to you.').classes('text-grey-5 text-sm')
            else:
                ui.label('Request submitted. The operator app will pick it up shortly.') \
                    .classes('text-grey-5')
        if uid:
            ui.notify('Measurement request created ✓', type='positive', timeout=6000)
    except Exception as e:
        ui.notify(f'Error: {e}', type='negative')
    finally:
        btn_submit.enable()


# ── Global UI refs ───────────────────────────────────────────────────────────
btn_submit = None
result_box = None


# ── Dark mode (element created per page build; never cache across clients) ──


# ── Page ─────────────────────────────────────────────────────────────────────
# ── Seiten rund um Benachrichtigungen und ELN ────────────────────────────────
# Antraege (mit Ergebnissen), das eigene eLabFTW-Ziel und die Konfiguration
# liegen in ui_notify und teilen Login, Token und Styling mit diesem Formular.
ui_notify.register(
    get_user=current_user,
    get_token=auth_token,
    accent=ACCENT,
    css=CSS,
    title=TITLE,
    open_login_js=OPEN_LOGIN_JS,
    nomad_api=nomad_api,
    state=st,
    navigate=lambda target: ui.navigate.to(target),
)


@ui.page('/')
def index(request: Request):
    ui.add_head_html(CSS)
    unit_refs.clear()  # widget refs are per page build
    rules_refs.clear()
    global method_input
    method_input = None
    cookie = request.cookies.get('Authorization', '')
    if cookie:
        st()['auth'] = cookie
    else:
        st().pop('auth', None)
    user = current_user()

    ui.colors(primary=ACCENT)

    # Gemeinsamer Kopf (ui_notify.header): gleiche Eintraege, gleiche Position
    # von Dunkelmodus und Name auf jeder Seite.
    ui_notify.header("New request", user)

    # ── Not signed in ──
    if not user:
        with ui.column().classes('tga-login-wrap items-center'):
            with ui.element('div').classes('tga-login-card'):
                ui.icon('lock', color=ACCENT).classes('text-5xl')
                ui.label('Signed in to NOMAD required').classes('tga-login-title')
                ui.label('This form uses your NOMAD account. Sign-in opens in a '
                         'separate window and closes automatically once you are '
                         'signed in, returning you to this page.').classes('tga-login-sub')
                ui.button('Sign in to NOMAD', icon='login')                     .on('click', js_handler=OPEN_LOGIN_JS)                     .props('unelevated size=lg').classes('tga-cta')
        ui.add_body_html(AUTH_POLL_JS)
        return

    # ── Form ──
    with ui.column().classes('w-full tga-page'):
        with ui.column().classes('w-full tga-hero'):
            ui.label(f'New measurement request').classes('tga-hero-title')
            ui.label('Describe the sample and the temperature program. Submitting creates '
                     'a NOMAD entry that the TGA operator will run on the instrument.') \
                .classes('tga-hero-sub')


        # 1. Sample
        with ui.element('div').classes('tga-panel'):
            with ui.row().classes('items-start gap-3 w-full'):
                ui.icon('science', color=ACCENT).classes('tga-section-icon')
                with ui.column().classes('gap-0'):
                    ui.label('1 · Sample').classes('tga-section-title')
                    ui.label('Name the sample and check it against the sample '
                             'requirements.').classes('tga-section-sub')
            # The lab's sample rules. Only what the software cannot check is
            # written out here - the mass limit is enforced by the field, and
            # what the requester has to confirm is one statement below.
            with ui.element('div').classes('tga-rules'):
                ui.label('Sample requirements').classes('tga-rules-title')
                for what, text in (
                    ('Size', f'max {PAN_MAX_MM} x {PAN_MAX_MM} mm - it has to fit the pan'),
                    ('Form', 'pieces or powder'),
                    ('Mass', f'aim for {MASS_OPT_MG:.0f} mg'),
                    ('Liquid', 'only if not volatile'),
                    ('Metal', 'alumina crucible only'),
                    ('Acids/bases', 'cannot be measured'),
                    ('Waiting', 'samples run in sequence, so yours may sit on the pan for '
                                'more than a day at room conditions'),
                ):
                    with ui.row().classes('tga-rules-row'):
                        ui.label(what).classes('tga-rules-what')
                        ui.label(text).classes('tga-rules-text')
            with ui.row().classes('w-full gap-4 mt-1'):
                with ui.column().classes('gap-1 flex-1'):
                    ui.label('Sample name *').classes('tga-label')
                    ui.input(value=get_form()['sample_name'],
                             on_change=lambda e: on_sample_name_change(e.value)) \
                        .props('outlined dense').classes('w-full')
                with ui.column().classes('gap-1 w-52'):
                    ui.label(f'Sample mass (mg) *').classes('tga-label')
                    # The 100 mg limit is not written down anywhere - the field
                    # refuses to take it (red + message) and the submit button
                    # would not get past validate() either.
                    unit_refs['sample_mass'] = ui.number(
                        value=get_form()['sample_mass'],
                        precision=3,
                        validation={f'Between 0 and {MASS_MAX_MG:.0f} mg': _mass_ok},
                        on_change=lambda e: on_mass_change(e.value)) \
                        .props('outlined dense').classes('w-full')
            # Crucible is optional: the instrument records the crucible it
            # actually used, so this is only the requester's preference.
            with ui.expansion('Crucible (optional)', icon='science').classes('tga-adv w-full mt-1'):
                ui.label('The crucible actually used is recorded by the instrument and '
                         'is included in the result file (TRIOS JSON). It is not yet '
                         'parsed into NOMAD. Use these fields only if you want to '
                         'request a specific crucible.').classes('tga-adv-note')
                with ui.row().classes('w-full gap-4 mt-1'):
                    with ui.column().classes('gap-1 w-48'):
                        ui.label('Crucible').classes('tga-label')
                        rules_refs['crucible'] = ui.select(
                            CRUCIBLES, value=get_form()['crucible_type'],
                            on_change=lambda e: get_form().update(crucible_type=e.value)) \
                            .props('outlined dense').classes('w-full')
                    # The crucible number is not the requester's to choose: the
                    # operators assign each sample to one of the lab's crucible
                    # slots in the order the requests arrive (see the requests
                    # page for the current assignment).

            # Everything the software cannot check is stated once. If the sample
            # does not fulfil the requirements, the way to go is the consultation
            # above the submit button, not a submission.
            with ui.column().classes('gap-1 w-full mt-3'):
                ui.checkbox('My sample fulfils the requirements above.',
                            value=get_form()['rules_ack'],
                            on_change=lambda e: get_form().update(rules_ack=bool(e.value)))
                ui.label('If it does not, or you are unsure, clarify it with the lab by '
                         'email first - the form asks for that above the submit button.')\
                    .classes('tga-hint')
                ui.checkbox('Metallic sample (alumina crucible).',
                            value=get_form()['metallic'],
                            on_change=lambda e: on_metallic_change(e.value))

        # 2. Atmosphere
        with ui.element('div').classes('tga-panel'):
            with ui.row().classes('items-start gap-3 w-full'):
                ui.icon('air', color=ACCENT).classes('tga-section-icon')
                with ui.column().classes('gap-0'):
                    ui.label('2 · Atmosphere & gases').classes('tga-section-title')
                    ui.label('Choose the purge gas. The purge gas flows are part of '
                             'the instrument setup and are fixed by the lab.').classes('tga-section-sub')
                    ui.label('Only nitrogen and air are set up - any other atmosphere '
                             'needs a consultation first.').classes('tga-hint')
            with ui.row().classes('w-full gap-4 mt-1'):
                with ui.column().classes('gap-1 w-48'):
                    ui.label('Purge gas').classes('tga-label')
                    ui.select(GASES, value=get_form()['gas_atmosphere'],
                              on_change=lambda e: (get_form().update(gas_atmosphere=e.value),
                                                   update_method_suggestion())) \
                        .props('outlined dense').classes('w-full')
                # Flow rates are the lab's instrument setup, not the requester's
                # choice (see LAB_SAMPLE_FLOW). Shown for information only, and
                # written into the request by build_archive.
                with ui.column().classes('gap-1'):
                    ui.label('Purge gas flows (set by the lab)').classes('tga-label')
                    ui.label(f'Sample {LAB_SAMPLE_FLOW:g} {LAB_FLOW_UNIT}  ·  '
                             f'Balance {LAB_BALANCE_FLOW:g} {LAB_FLOW_UNIT}') \
                        .classes('tga-adv-note')
                    ui.label('Tell the lab by email if your measurement needs '
                             'different flows.') \
                        .classes('tga-hint')

            # MS coupling belongs to the gas path: it analyses the purge gas
            # leaving the instrument. It is possible, but only after a
            # consultation - which the block above the submit button collects.
            with ui.column().classes('gap-1 w-full mt-2'):
                ui.checkbox('Mass-spectrometer coupled measurement '
                            '(measures the evolved gas).',
                            value=get_form()['ms_coupling'],
                            on_change=lambda e: on_coupling_change(e.value))

        # 3. Temperature program
        with ui.element('div').classes('tga-panel'):
            with ui.row().classes('items-start gap-3 w-full'):
                ui.icon('show_chart', color=ACCENT).classes('tga-section-icon')
                with ui.column().classes('gap-0 flex-1'):
                    ui.label('3 · Temperature program').classes('tga-section-title')
                    ui.label('Segments run in the order shown. Add as many as you need: ramps '
                             'and holds; the gas flow steps are set by the lab. Pick the '
                             'units you want to enter values in.').classes('tga-section-sub')
                    ui.label('A run longer than 1 day needs a consultation first '
                             '(the estimate below the segments shows where you are).') \
                        .classes('tga-hint')
            with ui.row().classes('w-full gap-3 items-end mt-2'):
                with ui.column().classes('gap-1 w-32'):
                    ui.label('Temperature').classes('tga-label')
                    ui.select(UNIT_TEMP, value=get_form()['temp_unit'],
                              on_change=lambda e: change_unit(
                                  'temp', e.value, seg_keys=['end_temp'])) \
                        .props('outlined dense').classes('w-full')
                with ui.column().classes('gap-1 w-32'):
                    ui.label('Rate').classes('tga-label')
                    ui.select(UNIT_RATE, value=get_form()['rate_unit'],
                              on_change=lambda e: change_unit(
                                  'rate', e.value, seg_keys=['rate'])) \
                        .props('outlined dense').classes('w-full')
                with ui.column().classes('gap-1 w-32'):
                    ui.label('Hold time').classes('tga-label')
                    ui.select(UNIT_TIME, value=get_form()['time_unit'],
                              on_change=lambda e: change_unit(
                                  'time', e.value, seg_keys=['duration_min'])) \
                        .props('outlined dense').classes('w-full')
            global seg_container
            seg_container = ui.column().classes('w-full gap-3 mt-1')
            rebuild_segments()
            ui.button('+ Add segment', icon='add', on_click=add_segment) \
                .props('outline dense').classes('self-start tga-addseg')
            # the >1 day rule depends on the program, so show the estimate
            rules_refs['runtime'] = ui.label('').classes('tga-hint')

        # 4. Method & contact
        with ui.element('div').classes('tga-panel'):
            with ui.row().classes('items-start gap-3 w-full'):
                ui.icon('edit_note', color=ACCENT).classes('tga-section-icon')
                with ui.column().classes('gap-0 flex-1'):
                    ui.label('4 · Method & contact').classes('tga-section-title')
                    ui.label('Anything the operator should know, and where the result '
                             'should go.').classes('tga-section-sub')
            # Prefilled from the NOMAD session (the email is in the login token,
            # NOMAD reads it the same way) and stored with the request, because
            # NOMAD's own user record does not carry an address here - without
            # this the requester cannot be reached when the measurement is done.
            with ui.column().classes('gap-1 w-full mt-1'):
                ui.label('Your email *').classes('tga-label')
                unit_refs['requester_email'] = ui.input(
                    value=get_form()['requester_email'],
                    on_change=lambda e: get_form().update(
                        requester_email=(e.value or '').strip())) \
                    .props('outlined dense').classes('w-full')
                ui.label('Taken from your NOMAD login - change it if the result should '
                         'go somewhere else.').classes('tga-hint')
            # Method name is optional and pre-filled from the segments: it is
            # patched into the .tprc and becomes the procedure name in TRIOS.
            with ui.expansion('Method name (optional)', icon='label').classes('tga-adv w-full mt-1'):
                ui.label('Suggested from the temperature program above and written into '
                         'the .tprc file, where it becomes the procedure name in TRIOS. '
                         'Edit it if you prefer a different name.').classes('tga-adv-note')
                method_input = ui.input(value=get_form()['procedure_name'],
                                        on_change=lambda e: get_form().update(
                                            procedure_name=e.value)) \
                    .props('outlined dense').classes('w-full')
            with ui.column().classes('gap-1 w-full mt-2'):
                ui.label('Comments (optional)').classes('tga-label')
                ui.textarea(value=get_form()['comments'],
                            on_change=lambda e: get_form().update(comments=e.value)) \
                    .props('outlined dense autogrow').classes('w-full')

        # Consultation gate - stays empty unless this request needs one
        # (metallic sample, MS coupling, run above a day). validate() requires
        # its checkbox in exactly those cases.
        rules_refs['consult'] = ui.column().classes('w-full')

        # Submit
        with ui.row().classes('w-full items-center gap-4 py-4'):
            global btn_submit
            btn_submit = ui.button('Create measurement request', icon='send',
                                   on_click=submit).props('unelevated size=lg').classes('tga-cta')
        global result_box
        result_box = ui.column().classes('w-full items-center gap-2')

        # initial state of the live rule hints
        update_runtime_label()
        update_consult_box()
        # the email sits in the login token; read it once the page exists
        ui.timer(0.6, prefill_session_fields, once=True)


ui.run(host='0.0.0.0', port=int(os.environ.get('PORT', '8090')),
       title=TITLE, storage_secret=os.environ.get('STORAGE_SECRET', uuid.uuid4().hex),
       reload=False, show=False, language='en')
