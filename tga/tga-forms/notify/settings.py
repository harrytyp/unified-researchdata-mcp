"""Settings for the TGA notifications, the ELN export and the admin backend.

Two JSON files hold the configuration:

* ``settings.json`` - what an administrator sets up once: the mail account, who
  gets operator notifications, the default eLabFTW target, which events send a
  mail, and who may open the admin page.
* ``users.json`` - one entry per requester: their own eLabFTW instance, API key
  and team.

The second file exists because the ELN export must not be tied to one
installation: the same code targets the lab's own eLabFTW, a university
instance or a personal one, and every user picks their own.

Secrets (the SMTP password and the eLabFTW API keys) live in these files. They
are never logged, never committed and never handed back to a browser in clear
text - the admin page writes them and is only ever told *whether* one is set.

Writes are atomic (temp file plus ``os.replace``) and the files are created with
mode 0600: a half-written file would lose the whole configuration, and a
world-readable one would leak the API keys.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from typing import Any, Dict, List, Optional

# Where the shared volume is mounted in the containers. Overridable so tests can
# point somewhere harmless instead of at a real configuration.
DATA_DIR = os.environ.get("TGA_CONFIG_DIR", "/data")

SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
USERS_FILE = os.path.join(DATA_DIR, "users.json")
OUTBOX_FILE = os.path.join(DATA_DIR, "outbox.jsonl")
SENT_FILE = os.path.join(DATA_DIR, "sent.jsonl")
# Merker gegen doppelte Mails: NOMAD verarbeitet einen Upload mehrfach
# (z. B. einmal fuer die .json und einmal fuer die .gz), und jede
# Verarbeitung meldet sich. Nur ein geaenderter Stand verschickt erneut.
NOTIFIED_FILE = os.path.join(DATA_DIR, "notified.json")
# The account that may open the admin page. Only Kolja Knodel for now - the page
# writes mail credentials and API keys, so it is not for everyone. Listed by
# name, user name, email and NOMAD user id: a login token may carry some of them
# (the Keycloak token has name and email, a NOMAD token only the id), and the
# comparison normalises the spelling ("Kolja Knodel" == "kolja.knodel").
DEFAULT_ADMINS = ["kolja.knodel", "kolja", "41875c3d-785d-4c2f-a7f5-1c81e6290276"]

DEFAULTS: Dict[str, Any] = {
    "mail": {
        "host": "",
        "port": 587,
        "starttls": True,
        "username": "",
        "password": "",
        "from_address": "",
        "from_name": "TGA Lab",
        "reply_to": "",
    },
    "recipients": {
        # Die Labor-Kontakte sind zugleich die Empfaenger der Operator-Mails:
        # sie fuehren die Messungen durch. Beides bleibt in der Konfiguration
        # aenderbar, damit ein neues Konto nicht im Code haengt.
        "operators": ["p.braun@tum.de", "luca.reichert@tum.de"],
        "lab_contacts": {
            "consultation": "p.braun@tum.de, luca.reichert@tum.de",
            "pedro": "p.braun@tum.de",
            "luca": "luca.reichert@tum.de",
        },
        "drop_off": (
            "TUM School of Engineering and Design\n"
            "Department of Materials Engineering\n"
            "Lehrstuhl fuer Werkstoffwissenschaften\n"
            "Boltzmannstr. 15\n"
            "85748 Garching\n"
            "Room MW 2228"
        ),
    },
    "notifications": {
        "request_created_operator": True,
        "request_created_user": True,
        "results_ready_user": True,
        "results_ready_operator": True,
        "moved_to_elabftw": True,
        "processing_failed_operator": True,
    },
    "elabftw": {
        "instance_url": "",
        "api_key": "",
        "team": "",
        "category": "",
    },
    "admins": DEFAULT_ADMINS,
    "links": {
        "nomad_base": "https://researchmcp.duckdns.org/nomad-oasis",
        # Oeffentliche Adresse fuer Links in Mails: die kurzen Wege
        # (/requests, /eln/<id>) leiten in den App-Pfad um, in dem die
        # NOMAD-Session liegt - kurz genug zum Abtippen.
        "form_app": "https://researchmcp.duckdns.org",
    },
}

_SECRET_PATHS = (
    ("mail", "password"),
    ("elabftw", "api_key"),
)


def _merge(base: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    """Deep merge, with lists replaced instead of appended.

    Merging matters because a caller only ever sends the fields it changed: a
    shallow update would drop the nested blocks it did not mention.
    """
    out = dict(base)
    for key, value in (patch or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def _read_json(path: str, fallback: Dict[str, Any]) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else dict(fallback)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return dict(fallback)


def _write_json(path: str, data: Dict[str, Any]) -> None:
    """Atomic write with 0600 - a lost configuration or a leaked key is worse
    than a failed write."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=os.path.dirname(path) or ".",
        prefix=".settings-", suffix=".tmp", delete=False)
    try:
        json.dump(data, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    finally:
        handle.close()
    os.chmod(handle.name, 0o600)
    os.replace(handle.name, path)


def load_settings() -> Dict[str, Any]:
    """Current settings, defaults filled in for anything not configured yet."""
    return _merge(DEFAULTS, _read_json(SETTINGS_FILE, {}))


def save_settings(patch: Dict[str, Any]) -> Dict[str, Any]:
    """Apply a patch and return the merged result.

    An empty string for a secret means "leave it alone", not "clear it": the
    browser never receives the current value, so a form that is saved without
    touching the password field would otherwise wipe it.
    """
    current = load_settings()
    incoming = dict(patch or {})
    for section, field in _SECRET_PATHS:
        block = incoming.get(section)
        if isinstance(block, dict) and block.get(field) == "":
            block.pop(field)
    merged = _merge(current, incoming)
    _write_json(SETTINGS_FILE, merged)
    return merged


def public_view(settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Settings as the browser may see them: secrets replaced by a yes/no.

    The admin page still has to show whether a password or key is set, otherwise
    nobody can tell a working setup from an unfinished one - but the value
    itself never leaves the server.
    """
    view = _merge(DEFAULTS, settings or load_settings())
    for section, field in _SECRET_PATHS:
        block = view.get(section)
        if isinstance(block, dict):
            block[field] = ""
            block[field + "_set"] = bool((settings or load_settings())
                                         .get(section, {}).get(field))
    return view


def _norm_identity(value: Any) -> str:
    """Fold an identifier so the spellings of one person are comparable.

    "Kolja Knodel", "kolja.knodel" and "Kolja_Knodel" all become "koljaknodel" -
    a login token carries the display name while the settings hold the user name,
    and matching them literally would lock the admin out of their own page.
    """
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def is_admin(user: Optional[Dict[str, Any]]) -> bool:
    """May this NOMAD user open the admin page?

    Matched on user name, display name, email (also its local part) and the
    NOMAD user id, because which of them a token carries depends on how the user
    signed in.
    """
    if not user:
        return False
    allowed = {_norm_identity(name) for name in load_settings().get("admins", [])}
    email = str(user.get("email") or "")
    candidates = {_norm_identity(value) for value in (
        user.get("username"), user.get("name"), email, email.split("@")[0],
        user.get("sub"), user.get("user"), user.get("user_id"))}
    return bool((candidates - {""}) & (allowed - {""}))


# ── Per-user eLabFTW targets ────────────────────────────────────────────────

def _user_key(user: Optional[Dict[str, Any]]) -> str:
    """Stable key for a user: prefer the email, fall back to the user name.

    Both appear in the login token; the email is the one the requester
    recognises, and the export is configured per person.
    """
    if not user:
        return ""
    return str(user.get("email") or user.get("username") or user.get("name") or "").lower()


def user_elabftw(user: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The eLabFTW target for this user: their own settings over the default.

    Field by field, so a user who only enters an API key still inherits the
    instance URL an administrator configured.
    """
    users = _read_json(USERS_FILE, {})
    own = users.get(_user_key(user)) or {}
    return _merge(load_settings().get("elabftw", {}), own.get("elabftw", {}))


def save_user_elabftw(user: Optional[Dict[str, Any]], values: Dict[str, Any]) -> Dict[str, Any]:
    """Store this user's eLabFTW target. Empty API key means "keep the old one"."""
    key = _user_key(user)
    if not key:
        raise ValueError("no user to store an eLabFTW target for")
    users = _read_json(USERS_FILE, {})
    entry = users.setdefault(key, {})
    current = entry.get("elabftw", {})
    incoming = {k: v for k, v in (values or {}).items() if k != "api_key" or v != ""}
    entry["elabftw"] = _merge(current, incoming)
    _write_json(USERS_FILE, users)
    return entry["elabftw"]


# ── Outbox and audit trail ──────────────────────────────────────────────────

def outbox_append(record: Dict[str, Any], path: str = OUTBOX_FILE) -> None:
    """Queue a mail that could not be sent yet (JSON lines, append only)."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    record = dict(record)
    record.setdefault("queued_at", time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    os.chmod(path, 0o600)


def outbox_read(path: str = OUTBOX_FILE) -> list:
    records = []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except FileNotFoundError:
        pass
    return records


def outbox_replace(records: list, path: str = OUTBOX_FILE) -> None:
    """Rewrite the outbox after a flush (used to keep the failures only)."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    os.chmod(path, 0o600)


def log_sent(record: Dict[str, Any], path: str = SENT_FILE) -> None:
    """Audit trail: who was told what, when. Never contains a secret."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    record = dict(record)
    record.setdefault("sent_at", time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    os.chmod(path, 0o600)


def sent_read(limit: int = 50, path: str = SENT_FILE) -> list:
    return outbox_read(path)[-limit:]


def was_notified(key: str, path: str = NOTIFIED_FILE) -> str:
    """Fingerprint of the last notification sent for this key ("" if none).

    The key is the upload; the fingerprint describes the result state, so a
    re-processing with the same values stays silent while a new measurement in
    the same upload still notifies.
    """
    return str(_read_json(path, {}).get(str(key), ""))


def mark_notified(key: str, fingerprint: str, path: str = NOTIFIED_FILE) -> None:
    data = _read_json(path, {})
    data[str(key)] = str(fingerprint)
    _write_json(path, data)
