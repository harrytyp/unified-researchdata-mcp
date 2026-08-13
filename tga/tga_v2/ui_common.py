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
