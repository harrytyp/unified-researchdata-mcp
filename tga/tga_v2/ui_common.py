"""Shared UI helpers: status colors, drag source, selection set."""
from nicegui import ui

# Status → Farbe (durchgängig: Badge, Kartenkante, Slot-Ring)
STATUS_COLORS = {
    'pending': 'amber',
    'received': 'sky',
    'assigned': 'deep-purple',
    'measured': 'emerald',
}

STATUS_COLUMN_HEADERS = {
    'pending': 'Angekommen',
    'received': 'Im Labor',
    'assigned': 'Im Pan',
    'measured': 'Gemessen',
}

STATUS_COLUMN_HEADERS_EN = {
    'pending': 'Arrived',
    'received': 'In lab',
    'assigned': 'In pan',
    'measured': 'Measured',
}

# Drag & Drop state (single-user desktop app → module-level is fine)
drag_source: str | None = None  # upload_id of the card being dragged

# Selection shared across board + list + action bar
selected: set[str] = set()

NUM_SLOTS = 30

# Length of the short sample id shown to humans (the first characters of the
# NOMAD upload_id). 5 characters are still 62^5 ~ 9e8 combinations, far beyond
# any lab's sample count, and 5 characters are what fits on a crucible. Any
# short id is a pure prefix of the full upload_id, so it can always be matched
# back to the id NOMAD and the entry use.
SAMPLE_ID_LEN = 5


def sample_id(upload_id: str | None) -> str:
    """Short, hand-writable form of the NOMAD upload_id.

    The form hands this code to the requester as soon as the request is
    submitted, the requester writes it on the crucible, and the operator sees
    the same code on the board card and in the detail panel. The full
    upload_id stays authoritative everywhere (NOMAD, deep links).

    NOTE: the length is mirrored in tga/tga-forms/app.py and in the NOMAD
    plugin (instrument_data/sample_id.py) - keep them in sync.
    """
    return (upload_id or '')[:SAMPLE_ID_LEN]


def set_drag_source(uid: str | None):
    global drag_source
    drag_source = uid


def status_color(status: str) -> str:
    return STATUS_COLORS.get(status, 'grey')


def column_header(cfg, status: str) -> str:
    """Column header in the configured language."""
    if cfg.get('language') == 'de':
        return STATUS_COLUMN_HEADERS[status]
    return STATUS_COLUMN_HEADERS_EN[status]


def select(uid: str):
    selected.add(uid)


def deselect(uid: str):
    selected.discard(uid)


def toggle_select(uid: str):
    if uid in selected:
        selected.discard(uid)
    else:
        selected.add(uid)


def clear_selection():
    selected.clear()


# ── i18n (strings dict injected by main.py) ────────────────────
_STRINGS: dict = {}
_lang: str = 'en'


def set_i18n(strings: dict, lang: str):
    global _STRINGS, _lang
    _STRINGS = strings
    _lang = lang


def _(key: str) -> str:
    return _STRINGS.get(key, {}).get(_lang, _STRINGS.get(key, {}).get('en', key))
