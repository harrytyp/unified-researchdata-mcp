"""The pages around the notifications: my requests, my ELN, the admin backend.

Three pages and two internal endpoints, all served by the form app itself, so
they inherit the NOMAD login through the same cookie path as the form and need
no extra route in the reverse proxy:

* ``/requests`` - what the requester submitted and where it stands. From here the
  data is pushed to eLabFTW or downloaded as a package for a manual upload.
* ``/eln`` - each user's own eLabFTW target: instance, API key, team. The export
  is deliberately not tied to one installation.
* ``/admin`` - the configuration behind it: mail account, recipients, which
  events notify whom, eLabFTW defaults, the queue of not-yet-sent mails and the
  audit trail. Only the accounts listed in the settings may open it.

The app hands over its own helpers (user, token, styling) through ``register``,
so this module stays independent of app.py and can be tested on its own.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, Callable, Dict, List, Optional

from fastapi import Request
from fastapi.responses import Response
from nicegui import app as nicegui_app
from nicegui import ui

from notify import elabftw as elabftw_mod
from notify import eln_export, entry_data, events, mailer
from notify import settings as settings_mod

log = logging.getLogger("tga.pages")

# Filled by register(); the pages call through these into the form app.
_api: Dict[str, Any] = {}

INTERNAL_SECRET = os.environ.get("STORAGE_SECRET", "")


def register(*, get_user: Callable[[], Optional[dict]], get_token: Callable[[], str],
             accent: str, css: str, title: str, open_login_js: str,
             nomad_api, state: Callable[[], dict], navigate) -> None:
    """Take over what the pages need from the form app (called once at startup)."""
    _api.update(get_user=get_user, get_token=get_token, accent=accent, css=css,
                title=title, open_login_js=open_login_js, api=nomad_api,
                state=state, navigate=navigate)
    _register_endpoints()


def _accent() -> str:
    return _api.get("accent", "#ff6d00")


# ── shared pieces ───────────────────────────────────────────────────────────

def _head() -> None:
    """Same stylesheet as the form, so the pages look like one application."""
    if _api.get("css"):
        ui.add_head_html(_api["css"])


def _header(active: str, user: Optional[dict]) -> None:
    with ui.header().classes("tga-header items-center px-4 gap-3 no-shadow"):
        with ui.row().classes("items-center gap-2"):
            ui.icon("whatshot", color=_accent()).classes("text-2xl")
            ui.label(_api.get("title", "TGA")).classes("tga-brand")
        ui.space()
        for label, target in (("New request", "/"),
                              ("My requests", "/requests"),
                              ("My ELN", "/eln"),
                              ("TGA", "/nomad-oasis/gui")):
            ui.button(label, on_click=lambda t=target: _api["navigate"](t)) \
                .props("flat dense " + ("color=white" if label == active else "")) \
                .classes("tga-header-btn")
        if user and settings_mod.is_admin(user):
            ui.button("Admin", on_click=lambda: _api["navigate"]("/admin")) \
                .props("flat dense").classes("tga-header-btn")
        ui.icon("account_circle").classes("text-grey-4")
        ui.label(_display_name(user)).classes("tga-user")


def _display_name(user: Optional[dict]) -> str:
    """What to show for the signed-in user.

    The claims differ by login route: a Keycloak session carries name and email,
    a NOMAD token only the user id. Showing the id is honest, an empty field is
    not.
    """
    user = user or {}
    return str(user.get("name") or user.get("username") or user.get("email")
               or user.get("sub") or user.get("user") or "not signed in")


def _identified(user: Optional[dict]) -> bool:
    """Is there enough of a user to work with?"""
    user = user or {}
    # "user" traegt die Kennung in einem NOMAD-Simple-Token, "sub" die im
    # Keycloak-Token - beides heisst: es ist jemand angemeldet.
    return bool(user.get("username") or user.get("name")
                or user.get("email") or user.get("sub") or user.get("user"))


def _needs_login(user: Optional[dict], what: str = "This page") -> bool:
    """Show the same sign-in card as the form and tell whether to stop.

    The sign-in dance is the form's (separate window, returns automatically), so
    it is reused verbatim instead of inventing a second one.
    """
    if _identified(user):
        return False
    with ui.column().classes("tga-login-wrap items-center"):
        with ui.element("div").classes("tga-login-card"):
            ui.icon("lock", color=_accent()).classes("text-5xl")
            ui.label("Signed in to NOMAD required").classes("tga-login-title")
            ui.label(f"{what} uses your NOMAD account.").classes("tga-login-sub")
            ui.button("Sign in to NOMAD", icon="login") \
                .on("click", js_handler=_api.get("open_login_js", "")) \
                .props("unelevated size=lg").classes("tga-cta")
    return True


def _gui_url(upload_id: str, entry_id: str = "") -> str:
    base = settings_mod.load_settings().get("links", {}).get("nomad_base", "").rstrip("/")
    if entry_id:
        return f"{base}/gui/user/uploads/upload/id/{upload_id}/entry/id/{entry_id}"
    return f"{base}/gui/user/uploads/upload/id/{upload_id}"


def _my_uploads(token: str, limit: int = 50) -> List[Dict[str, Any]]:
    """The uploads this token may see - the API decides, not this code.

    Everything the pages read afterwards (the archive included) is limited to
    what comes back here, which is what keeps the file read permission-correct.
    """
    status, response = _api["api"].api_json(
        "GET", f"/uploads?page_size={limit}&order=desc", token)
    if status != 200:
        return []
    data = response.get("data") if isinstance(response, dict) else None
    uploads = data.get("uploads") if isinstance(data, dict) else data
    return [u for u in (uploads or []) if isinstance(u, dict)]


def _request_row(upload: Dict[str, Any], token: str) -> Dict[str, Any]:
    upload_id = str(upload.get("upload_id") or "")
    name = str(upload.get("upload_name") or "")
    code = upload_id[:5]
    fields = entry_data.read_fields(upload_id)
    res = entry_data.results(fields)
    return {
        "upload_id": upload_id,
        "upload_name": name,
        "code": code,
        "sample": res.get("sample_name") or name,
        # "ready" heisst gemessen, nicht "hat Ergebnis-Schluessel": ein Antrag
        # liefert schon den Probennamen, galt damit aber faelschlich als fertig.
        "ready": entry_data.is_measured(fields),
        "results": res,
        "created": str(upload.get("upload_create_time") or "")[:10],
        "created_raw": str(upload.get("upload_create_time") or ""),
        "gui_url": _gui_url(upload_id),
    }


def _pending_requests(token: str) -> List[Dict[str, Any]]:
    """Requests waiting for their measurement, oldest first.

    Oldest first is the order the operators work in and therefore the order the
    crucible slots are handed out in.
    """
    rows = [_request_row(upload, token) for upload in _my_uploads(token)]
    pending = [row for row in rows
               if not row["ready"]
               and row["upload_name"].startswith("TGA Request")]
    return sorted(pending, key=lambda row: row["created_raw"])


# ── my requests ─────────────────────────────────────────────────────────────

@ui.page("/requests")
def page_requests(request: Request) -> None:
    _head()
    token = _api["api"].token_from_request(request) if hasattr(_api["api"], "token_from_request") \
        else request.cookies.get("Authorization", "")
    if token:
        _api["state"]()["auth"] = token
    user = _api["get_user"]()
    _header("My requests", user)
    if _needs_login(user, "The request list"):
        return

    with ui.column().classes("w-full tga-page"):
        with ui.column().classes("w-full tga-hero"):
            ui.label("My measurement requests").classes("tga-hero-title")
            ui.label("Everything you submitted, with the results when the measurement "
                     "is done. From here you can push a finished measurement to your "
                     "ELN or download it.").classes("tga-hero-sub")

        container = ui.column().classes("w-full gap-3")

        def refresh() -> None:
            container.clear()
            with container:
                rows = [_request_row(u, token) for u in _my_uploads(token)]
                # Nur echte TGA-Antraege bzw. Messungen: im Oasis liegen auch
                # Test- und Staging-Uploads des Betriebs, die hier nichts zu
                # suchen haben und die Liste unlesbar machen.
                rows = [r for r in rows
                        if r["upload_name"].startswith("TGA Request") or r["ready"]]
                if not rows:
                    ui.label("No requests yet.").classes("text-grey-5")
                    return
                for row in rows:
                    _request_card(row, token, refresh)

        refresh()

        with ui.row().classes("items-center gap-2"):
            ui.button("Refresh", icon="refresh", on_click=refresh).props("flat dense")
            ui.button("ELN settings", icon="settings",
                      on_click=lambda: _api["navigate"]("/eln")).props("flat dense")


def _request_card(row: Dict[str, Any], token: str, refresh) -> None:
    """One request: what it is, where it stands and what can be done with it."""
    with ui.element("div").classes("tga-panel w-full"):
        with ui.row().classes("items-center gap-3 w-full"):
            ui.icon("check_circle" if row["ready"] else "hourglass_top",
                    color="#16a34a" if row["ready"] else "#f59e0b").classes("text-2xl")
            with ui.column().classes("gap-0 grow"):
                ui.label(f"{row['sample']}").classes("text-lg font-medium")
                slot = settings_mod.pan_slot_get(row["upload_id"])
                ui.label(f"Code {row['code']}  |  {row['created']}  |  "
                         f"{'results ready' if row['ready'] else 'waiting for the measurement'}"
                         + (f"  |  crucible slot {slot}" if slot else "")
                         ).classes("text-sm text-grey-5")
            if row["ready"]:
                for label, value in row["results"].items():
                    if label in ("sample_name", "procedure"):
                        continue
                    ui.label(f"{label.replace('_', ' ')}: {value}").classes("text-sm")
            ui.button("Open in NOMAD", icon="open_in_new",
                      on_click=lambda url=row["gui_url"]: _api["navigate"](url)) \
                .props("flat dense")

        if row["ready"]:
            with ui.row().classes("items-center gap-2 mt-2"):
                ui.button("Download for ELN", icon="download",
                          on_click=lambda u=row: ui.navigate.to(
                              download_url(u["upload_id"]), new_tab=True)) \
                    .props("outline dense")
                ui.button("Send to eLabFTW", icon="science",
                          on_click=lambda u=row: _export_dialog(u, token, refresh)) \
                    .props("unelevated dense")


def _export_dialog(row: Dict[str, Any], token: str, refresh) -> None:
    """Confirm the target, then export - the instance and key are the user's."""
    user = _api["get_user"]()
    target = settings_mod.user_elabftw(user)
    with ui.dialog() as dialog, ui.card().classes("gap-3"):
        ui.label(f"Send {row['sample']} to eLabFTW").classes("text-lg font-medium")
        if not target.get("instance_url") or not target.get("api_key"):
            ui.label("No eLabFTW target is set for your account yet. Add your instance, "
                     "team and API key under 'My ELN' first.").classes("text-sm")
            ui.button("Open ELN settings", on_click=lambda: _api["navigate"]("/eln")) \
                .props("flat dense")
        else:
            ui.label(f"Instance: {target.get('instance_url')}").classes("text-sm")
            ui.label(f"Team: {target.get('team') or '(default)'}").classes("text-sm")
            ui.label("This creates an experiment in your ELN with the parameters, the "
                     "results and the DTG figure.").classes("text-sm text-grey-5")
            report_box = ui.column().classes("w-full")

            def do_export() -> None:
                report_box.clear()
                with report_box:
                    ui.spinner()
                try:
                    summary = entry_data.request_summary(row["upload_id"])
                    ctx = _export_context(row, summary)
                    figure = eln_export.dtg_figure(summary["signals"],
                                                   f"TGA {row['code']} - {row['sample']}")
                    report = elabftw_mod.export_entry(
                        ctx, target, figure=figure,
                        filename=f"TGA_{row['code']}_dtg.png")
                    _remember_export(row["upload_id"], token, report, user)
                    events.notify("moved_to_elabftw",
                                  {**ctx, "elabftw_url": report.get("url", ""),
                                   "elabftw_instance": report.get("instance", ""),
                                   "elabftw_team": target.get("team", ""),
                                   "exported_by": str((user or {}).get("name") or "")})
                except Exception as error:                      # noqa: BLE001
                    report = {"ok": False, "error": f"{type(error).__name__}: {error}"}
                report_box.clear()
                with report_box:
                    if report.get("ok"):
                        with ui.element("div").classes("tga-success-title"):
                            ui.icon("check_circle", color="#16a34a")
                            ui.label("Exported")
                        ui.link(report.get("url", ""), report.get("url", ""))
                        if not report.get("attached"):
                            ui.label("The figure could not be attached, the experiment "
                                     "was still created.").classes("text-sm text-grey-5")
                    else:
                        ui.label(f"Export failed: {report.get('error', '')}") \
                            .classes("text-sm text-red-400")
                refresh()

            with ui.row().classes("gap-2"):
                ui.button("Send now", icon="send", on_click=do_export).props("unelevated")
                ui.button("Cancel", on_click=dialog.close).props("flat")
        ui.button("Close", on_click=dialog.close).props("flat")
    dialog.open()


def _results_fingerprint(results: Dict[str, Any]) -> str:
    """Short, stable fingerprint of a result set (same values -> same string)."""
    import hashlib
    payload = json.dumps({k: v for k, v in sorted((results or {}).items())},
                         ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def _current_name() -> str:
    """Name of the signed-in user, or empty when there is no page context.

    The export and the notifications also run without a browser (from the
    processing callback), so this must not assume a session exists.
    """
    getter = _api.get("get_user")
    if not getter:
        return ""
    try:
        return str((getter() or {}).get("name") or "")
    except Exception:                              # noqa: BLE001
        return ""


def _export_context(row: Dict[str, Any], summary: Dict[str, Any]) -> Dict[str, Any]:
    """Context for eLabFTW and the mails: parameters, results, links, contacts."""
    settings = settings_mod.load_settings()
    window, delta = entry_data.dtg_settings(summary["fields"])
    return {
        "code": row["code"],
        "sample_name": row["sample"],
        "requester": _current_name() or summary.get("requester", ""),
        "requester_email": summary.get("requester", ""),
        "entry_url": row["gui_url"],
        "upload_url": row["gui_url"],
        "measured_on": row["created"],
        "operator": summary.get("operator", ""),
        "parameters": summary["parameters"],
        "results": summary["results"],
        "contacts": settings.get("recipients", {}).get("lab_contacts", {}),
        "drop_off": settings.get("recipients", {}).get("drop_off", ""),
        "dtg_window": window,
        "dtg_delta": delta,
        "exported_at": time.strftime("%Y-%m-%d %H:%M"),
        "requests_url": requests_url(),
        "download_url": (settings.get("links", {}).get("form_app", "").rstrip("/")
                         + f"/eln/{row['upload_id']}"),
    }


def requests_url() -> str:
    """Short address of the request page (for the mails)."""
    base = settings_mod.load_settings().get("links", {}).get("form_app", "").rstrip("/")
    return f"{base}/requests"


def download_url(upload_id: str) -> str:
    """Absolute link to the ELN package of one upload."""
    base = settings_mod.load_settings().get("links", {}).get("form_app", "").rstrip("/")
    return f"{base}/eln/{upload_id}"


def request_context(upload_id: str, archive: Dict[str, Any], requester: Optional[dict],
                    consultation: Optional[List[str]] = None) -> Dict[str, Any]:
    """The context for the mails about a freshly submitted request.

    Built from the archive the form just sent, so the mail says exactly what was
    submitted (same parameters, same units) - not a second rendering of the form
    that could drift from it.
    """
    data = (archive or {}).get("data") or archive or {}
    fields: Dict[str, Any] = {}
    entry_data._flatten(data, "", fields)
    settings = settings_mod.load_settings()
    requester = requester or {}
    return {
        "code": str(upload_id or "")[:5],
        "sample_name": str(fields.get("sample.sample_name") or ""),
        "requester": str(requester.get("name") or requester.get("username") or ""),
        "requester_email": str(fields.get("requester_email")
                               or requester.get("email") or ""),
        "entry_url": _gui_url(upload_id),
        "upload_url": _gui_url(upload_id),
        "requests_url": requests_url(),
        "drop_off": settings.get("recipients", {}).get("drop_off", ""),
        "contacts": settings.get("recipients", {}).get("lab_contacts", {}),
        "consultation": list(consultation or []),
        "parameters": entry_data.parameters(fields),
        "results": {},
    }


def notify_new_request(upload_id: str, archive: Dict[str, Any],
                       requester: Optional[dict],
                       consultation: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Tell the operators and the requester that a request arrived.

    Called after the upload exists, so the links in the mail work. Any failure is
    returned, never raised: a missing notification must not fail the request.
    """
    try:
        ctx = request_context(upload_id, archive, requester, consultation)
    except Exception as error:                     # noqa: BLE001
        log.exception("could not build the request notification")
        return [{"event": "request", "status": "context-error", "detail": str(error),
                 "recipients": []}]
    reports = []
    for event in ("request_created_operator", "request_created_user"):
        try:
            reports.append(events.notify(event, ctx))
        except Exception as error:                 # noqa: BLE001
            log.exception("notification %s failed", event)
            reports.append({"event": event, "status": "error", "detail": str(error),
                            "recipients": []})
    return reports


def _remember_export(upload_id: str, token: str, report: Dict[str, Any],
                     user: Optional[dict]) -> None:
    """Store the export with the upload, so the page shows it after a reload.

    Written as ordinary upload metadata: no schema change, and it is cleared with
    the upload. The API key is never part of it.
    """
    if not report.get("ok"):
        return
    payload = {
        "url": report.get("url", ""),
        "id": report.get("id", ""),
        "instance": report.get("instance", ""),
        "exported_by": str((user or {}).get("name") or ""),
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    try:
        _api["api"].api_json("POST", f"/uploads/{upload_id}/edit", token,
                             {"metadata": {"tga_elabftw": payload}})
    except Exception as error:                     # noqa: BLE001
        log.warning("could not store the export on the upload: %s", error)


# ── my ELN ──────────────────────────────────────────────────────────────────

@ui.page("/eln")
def page_eln(request: Request) -> None:
    _head()
    token = request.cookies.get("Authorization", "")
    if token:
        _api["state"]()["auth"] = token
    user = _api["get_user"]()
    _header("My ELN", user)
    if _needs_login(user, "The ELN settings"):
        return

    target = settings_mod.user_elabftw(user)
    defaults = settings_mod.load_settings().get("elabftw", {})
    with ui.column().classes("w-full tga-page"):
        with ui.column().classes("w-full tga-hero"):
            ui.label("My eLabFTW").classes("tga-hero-title")
            ui.label("Where your finished measurements are exported. Any eLabFTW "
                     "installation works: the lab's own, a university instance or a "
                     "private one. The API key is stored on the server and never "
                     "shown again.").classes("tga-hero-sub")

        with ui.element("div").classes("tga-panel w-full"):
            instance = ui.input("eLabFTW instance (URL)",
                                value=target.get("instance_url", "")).classes("w-full")
            api_key = ui.input("API key",
                               value="",
                               password=True, password_toggle_button=True).classes("w-full")
            if target.get("api_key"):
                api_key.props("hint='a key is stored - leave empty to keep it'")
            team = ui.input("Team", value=str(target.get("team") or "")).classes("w-full")
            verify = ui.checkbox("Verify TLS certificate",
                                 value=bool(target.get("verify_tls", True)))
            result_box = ui.column().classes("w-full gap-1")

            def collect() -> Dict[str, Any]:
                return {"instance_url": instance.value or "",
                        "api_key": api_key.value or "",
                        "team": team.value or "",
                        "verify_tls": bool(verify.value)}

            def save() -> None:
                settings_mod.save_user_elabftw(user, collect())
                result_box.clear()
                with result_box:
                    ui.label("Saved.").classes("text-sm").style("color:#16a34a")
                api_key.value = ""

            def test() -> None:
                values = collect()
                values["api_key"] = values["api_key"] or target.get("api_key", "")
                result_box.clear()
                with result_box:
                    if not values["api_key"] or not values["instance_url"]:
                        ui.label("Instance and API key are needed for the test.") \
                            .classes("text-sm text-amber-400")
                        return
                    ui.spinner()
                client = elabftw_mod.ElabFTWClient(
                    values["instance_url"], values["api_key"],
                    team=values["team"], verify_tls=values["verify_tls"])
                report = client.test_connection()
                result_box.clear()
                with result_box:
                    if report["ok"]:
                        ui.label(f"Connected to {report['instance']} "
                                 f"(version {report['version'] or 'unknown'})") \
                            .classes("text-sm").style("color:#16a34a")
                        if report["teams"]:
                            ui.label("Teams this key may write to: "
                                     + ", ".join(report["teams"])).classes("text-sm text-grey-5")
                            team.value = team.value or report["teams"][0].split(":")[0]
                        if report["error"]:
                            ui.label(report["error"]).classes("text-sm text-amber-400")
                    else:
                        ui.label(f"Not connected: {report['error']}") \
                            .classes("text-sm text-red-400")

            with ui.row().classes("gap-2"):
                ui.button("Save", icon="save", on_click=save).props("unelevated")
                ui.button("Test connection", icon="wifi_tethering", on_click=test) \
                    .props("outline")
                ui.button("Back to my requests",
                          on_click=lambda: _api["navigate"]("/requests")).props("flat")

        with ui.element("div").classes("tga-panel w-full"):
            ui.label("Lab default").classes("font-medium")
            ui.label(f"Instance: {defaults.get('instance_url') or '(not set yet)'}")\
                .classes("text-sm text-grey-5")
            ui.label(f"Team: {defaults.get('team') or '(default of the key)'}")\
                .classes("text-sm text-grey-5")


# ── admin backend ───────────────────────────────────────────────────────────

@ui.page("/admin")
def page_admin(request: Request) -> None:
    _head()
    token = request.cookies.get("Authorization", "")
    if token:
        _api["state"]()["auth"] = token
    user = _api["get_user"]()
    _header("Admin", user)

    if _needs_login(user, "The admin page"):
        return
    if not settings_mod.is_admin(user):
        with ui.column().classes("w-full tga-page"):
            with ui.element("div").classes("tga-panel w-full"):
                ui.icon("block", color="#f59e0b").classes("text-3xl")
                ui.label("Not enabled for this account").classes("text-lg font-medium")
                ui.label("This page configures the mail account and the API keys, so it "
                         "is limited to the accounts listed in the settings. Ask the "
                         "administrator to add you if you need access.").classes("text-sm")
        return

    settings = settings_mod.load_settings()
    state: Dict[str, Any] = {"settings": settings}

    with ui.column().classes("w-full tga-page"):
        with ui.column().classes("w-full tga-hero"):
            ui.label("TGA request system - settings").classes("tga-hero-title")
            ui.label("Mail account, recipients, notifications, eLabFTW defaults and the "
                     "queue. Everything is stored server side; passwords and API keys "
                     "are never shown again once saved.").classes("tga-hero-sub")

        _mail_panel(state)
        _recipient_panel(state)
        _notification_panel(state)
        _pan_slot_panel(token)
        _elabftw_panel(state)
        _queue_panel(state)
        _audit_panel(state)


def _save(state: Dict[str, Any], patch: Dict[str, Any], note: str = "") -> None:
    state["settings"] = settings_mod.save_settings(patch)
    ui.notify(note or "Saved", type="positive", position="top")


def _mail_panel(state: Dict[str, Any]) -> None:
    settings = state["settings"]
    mail = settings["mail"]
    ready, reason = mailer.is_configured(settings)
    with ui.element("div").classes("tga-panel w-full"):
        with ui.row().classes("items-center gap-2"):
            ui.icon("mail", color=_accent()).classes("text-2xl")
            ui.label("Mail account").classes("text-lg font-medium")
            ui.badge("configured" if ready else "not configured",
                     color="green" if ready else "amber")
        if not ready:
            ui.label(f"Sending is off ({reason}). Notifications are queued and go out "
                     "as soon as the account is set and the queue is flushed."
                     ).classes("text-sm text-grey-5")

        host = ui.input("SMTP host", value=mail["host"]).classes("w-full")
        port = ui.number("Port", value=mail["port"], format="%d").classes("w-32")
        starttls = ui.checkbox("STARTTLS (port 587)", value=bool(mail["starttls"]))
        username = ui.input("Username", value=mail["username"]).classes("w-full")
        password = ui.input("Password", value="", password=True,
                            password_toggle_button=True).classes("w-full")
        if mail.get("password"):
            password.props("hint='a password is stored - leave empty to keep it'")
        sender = ui.input("Sender address", value=mail["from_address"]).classes("w-full")
        sender_name = ui.input("Sender name", value=mail["from_name"]).classes("w-64")
        reply_to = ui.input("Reply-To", value=mail["reply_to"]).classes("w-full")

        def save_mail() -> None:
            _save(state, {"mail": {
                "host": host.value or "", "port": int(port.value or 587),
                "starttls": bool(starttls.value), "username": username.value or "",
                "password": password.value or "", "from_address": sender.value or "",
                "from_name": sender_name.value or "", "reply_to": reply_to.value or "",
            }})
            password.value = ""

        test_box = ui.column().classes("w-full gap-1")
        test_to = ui.input("Test mail to", value=sender.value or "").classes("w-80")

        def send_test() -> None:
            recipient = (test_to.value or "").strip()
            test_box.clear()
            with test_box:
                if not recipient:
                    ui.label("Enter an address for the test mail.").classes("text-sm text-amber-400")
                    return
                ui.spinner()
            status, detail = mailer.send_mail(
                "TGA test mail", "This is a test from the TGA request system.",
                recipient, config=settings_mod.load_settings(), event="test")
            test_box.clear()
            with test_box:
                if status == "sent":
                    ui.label(f"Test mail sent to {recipient}.").classes("text-sm") \
                        .style("color:#16a34a")
                elif status == "queued":
                    ui.label(f"Not sent yet: {detail}. The mail is in the queue."
                             ).classes("text-sm text-amber-400")
                else:
                    ui.label(f"Failed: {detail}").classes("text-sm text-red-400")

        with ui.row().classes("gap-2 items-center"):
            ui.button("Save", icon="save", on_click=save_mail).props("unelevated")
            ui.button("Send test mail", icon="send", on_click=send_test).props("outline")
            test_to


def _recipient_panel(state: Dict[str, Any]) -> None:
    recipients = state["settings"]["recipients"]
    contacts = recipients.get("lab_contacts", {})
    with ui.element("div").classes("tga-panel w-full"):
        with ui.row().classes("items-center gap-2"):
            ui.icon("groups", color=_accent()).classes("text-2xl")
            ui.label("Recipients").classes("text-lg font-medium")
        operators = ui.textarea(
            "Operator notifications (one address per line)",
            value="\n".join(recipients.get("operators", []))).classes("w-full")
        pedro = ui.input("Contact for sample drop-off", value=contacts.get("pedro", "")).classes("w-full")
        luca = ui.input("Second contact", value=contacts.get("luca", "")).classes("w-full")
        consultation = ui.input("Consultation address (both, comma separated)",
                                value=contacts.get("consultation", "")).classes("w-full")
        drop_off = ui.textarea("Drop-off address (shown in the request mail)",
                               value=recipients.get("drop_off", "")).classes("w-full")

        def save_recipients() -> None:
            _save(state, {"recipients": {
                "operators": [line.strip() for line in (operators.value or "").splitlines()
                              if line.strip()],
                "lab_contacts": {"pedro": pedro.value or "", "luca": luca.value or "",
                                 "consultation": consultation.value or ""},
                "drop_off": drop_off.value or "",
            }})

        ui.button("Save", icon="save", on_click=save_recipients).props("unelevated")


def _notification_panel(state: Dict[str, Any]) -> None:
    toggles = state["settings"]["notifications"]
    labels = {
        "request_created_operator": "New request -> operators",
        "request_created_user": "New request -> requester",
        "results_ready_user": "Results ready -> requester",
        "results_ready_operator": "Results ready -> operators",
        "moved_to_elabftw": "Exported to eLabFTW -> requester",
        "processing_failed_operator": "Processing failed -> operators",
    }
    with ui.element("div").classes("tga-panel w-full"):
        with ui.row().classes("items-center gap-2"):
            ui.icon("notifications", color=_accent()).classes("text-2xl")
            ui.label("Which event notifies whom").classes("text-lg font-medium")
        boxes = {event: ui.checkbox(label, value=bool(toggles.get(event, True)))
                 for event, label in labels.items()}
        ui.button("Save", icon="save",
                  on_click=lambda: _save(state, {"notifications": {
                      event: bool(box.value) for event, box in boxes.items()}})) \
            .props("unelevated")


def _elabftw_panel(state: Dict[str, Any]) -> None:
    settings = state["settings"]
    block = settings["elabftw"]
    with ui.element("div").classes("tga-panel w-full"):
        with ui.row().classes("items-center gap-2"):
            ui.icon("science", color=_accent()).classes("text-2xl")
            ui.label("eLabFTW default target").classes("text-lg font-medium")
        ui.label("Users can override instance, team and API key for themselves under "
                 "'My ELN'. What is set here is the fallback.").classes("text-sm text-grey-5")
        instance = ui.input("Instance (URL)", value=block.get("instance_url", "")).classes("w-full")
        key = ui.input("API key", value="", password=True,
                       password_toggle_button=True).classes("w-full")
        if block.get("api_key"):
            key.props("hint='a key is stored - leave empty to keep it'")
        team = ui.input("Team", value=str(block.get("team") or "")).classes("w-40")
        category = ui.input("Category", value=str(block.get("category") or "")).classes("w-60")
        box = ui.column().classes("w-full gap-1")

        def save_elabftw() -> None:
            _save(state, {"elabftw": {"instance_url": instance.value or "",
                                      "api_key": key.value or "",
                                      "team": team.value or "",
                                      "category": category.value or ""}})
            key.value = ""

        def test_elabftw() -> None:
            current = settings_mod.load_settings()["elabftw"]
            values = {"instance_url": instance.value or current.get("instance_url", ""),
                      "api_key": key.value or current.get("api_key", ""),
                      "team": team.value or current.get("team", "")}
            box.clear()
            with box:
                if not values["instance_url"] or not values["api_key"]:
                    ui.label("Instance and API key are needed for the test.") \
                        .classes("text-sm text-amber-400")
                    return
                ui.spinner()
            report = elabftw_mod.ElabFTWClient(values["instance_url"], values["api_key"],
                                               team=values["team"]).test_connection()
            box.clear()
            with box:
                if report["ok"]:
                    ui.label(f"Connected to {report['instance']} "
                             f"(version {report['version'] or 'unknown'})") \
                        .classes("text-sm").style("color:#16a34a")
                    if report["teams"]:
                        ui.label("Teams: " + ", ".join(report["teams"])).classes("text-sm text-grey-5")
                else:
                    ui.label(f"Not connected: {report['error']}").classes("text-sm text-red-400")

        with ui.row().classes("gap-2"):
            ui.button("Save", icon="save", on_click=save_elabftw).props("unelevated")
            ui.button("Test connection", icon="wifi_tethering", on_click=test_elabftw).props("outline")


def _pan_slot_panel(token: str) -> None:
    """Crucible slots: the operators hand them out, not the requesters.

    A requester cannot know which crucible their sample ends up in - that is a
    lab decision, and the number follows the order the requests arrived. The
    button numbers every waiting request accordingly; the first slots are the
    ones the lab keeps for external analyses.
    """
    external = settings_mod.external_slots()
    with ui.element("div").classes("tga-panel w-full"):
        with ui.row().classes("items-center gap-2"):
            ui.icon("grid_view", color=_accent()).classes("text-2xl")
            ui.label("Crucible slots").classes("text-lg font-medium")
            if external:
                ui.badge(f"{external} for external analyses", color="grey")
        ui.label("Requesters do not choose a crucible number. The button numbers every "
                 "waiting request in the order it arrived, so the sample registered "
                 "first gets the first slot. Assigned samples keep their number."
                 ).classes("text-sm text-grey-5")
        ui.label("The number is kept here and shown on the request page; NOMAD itself "
                 "does not accept extra fields on an upload, and the pan the "
                 "instrument used is recorded by the measurement anyway."
                 ).classes("tga-hint")

        box = ui.column().classes("w-full gap-1 mt-2")

        def refresh() -> None:
            assignments = settings_mod.pan_slots_read()
            rows = _pending_requests(token)
            box.clear()
            with box:
                if not rows:
                    ui.label("No request is waiting for a measurement.").classes("text-sm text-grey-5")
                    return
                for row in rows:
                    slot = assignments.get(row["upload_id"])
                    with ui.row().classes("items-center gap-2"):
                        ui.badge(f"slot {slot}" if slot else "not assigned",
                                 color="green" if slot else "amber")
                        ui.label(f"{row['sample']} ({row['code']})  |  registered {row['created']}"
                                 ).classes("text-sm")
                        if slot and external and int(slot) > external:
                            ui.label("beyond the external slots").classes("text-xs text-amber-400")

        def assign() -> None:
            rows = _pending_requests(token)
            if not rows:
                ui.notify("Nothing is waiting", type="warning", position="top")
                return
            assigned = settings_mod.pan_slots_assign([row["upload_id"] for row in rows])
            refresh()
            ui.notify(f"Assigned {len(assigned)} slot(s) by registration date",
                      type="positive", position="top")

        def clear() -> None:
            settings_mod.pan_slots_clear()
            refresh()
            ui.notify("Assignment cleared", position="top")

        refresh()
        with ui.row().classes("gap-3 mt-2 items-end"):
            ui.button("Assign by registration date", icon="format_list_numbered",
                      on_click=assign).props("unelevated")
            ui.button("Clear", icon="clear", on_click=clear).props("outline")
            ui.number("Slots for external analyses", value=external, min=0, max=50,
                      on_change=lambda e: settings_mod.save_settings(
                          {"pan_slots": {"external": int(e.value or 0)}})) \
                .props("outlined dense").classes("w-56")


def _queue_panel(state: Dict[str, Any]) -> None:
    summary = mailer.outbox_summary()
    with ui.element("div").classes("tga-panel w-full"):
        with ui.row().classes("items-center gap-2"):
            ui.icon("schedule_send", color=_accent()).classes("text-2xl")
            ui.label("Queue").classes("text-lg font-medium")
            ui.badge(str(summary["count"]), color="amber" if summary["count"] else "grey")
        if summary["count"]:
            ui.label(f"{summary['count']} notification(s) waiting, oldest "
                     f"{summary['oldest'] or 'unknown'}. They go out as soon as the mail "
                     "account works.").classes("text-sm text-grey-5")
        else:
            ui.label("Nothing waiting.").classes("text-sm text-grey-5")
        box = ui.column().classes("w-full gap-1")

        def flush() -> None:
            result = mailer.flush_outbox()
            box.clear()
            with box:
                if result.get("reason"):
                    ui.label(f"Still not possible: {result['reason']}").classes("text-sm text-amber-400")
                else:
                    ui.label(f"Sent {result.get('sent', 0)}, kept {result.get('kept', 0)}."
                             ).classes("text-sm")
            ui.notify("Queue processed", position="top")

        with ui.row().classes("gap-2"):
            ui.button("Send queued now", icon="outbox", on_click=flush).props("outline")
        box


def _audit_panel(state: Dict[str, Any]) -> None:
    with ui.element("div").classes("tga-panel w-full"):
        with ui.row().classes("items-center gap-2"):
            ui.icon("history", color=_accent()).classes("text-2xl")
            ui.label("Last notifications").classes("text-lg font-medium")
        entries = list(reversed(settings_mod.sent_read(15)))
        if not entries:
            ui.label("Nothing sent or queued yet.").classes("text-sm text-grey-5")
        for entry in entries:
            status = entry.get("status", "")
            colour = {"sent": "green", "queued": "amber", "failed": "red"}.get(status, "grey")
            with ui.row().classes("items-center gap-2"):
                ui.badge(status, color=colour)
                ui.label(f"{entry.get('sent_at', '')}  {entry.get('subject', '')}  -> "
                         f"{', '.join(entry.get('to', []))}").classes("text-sm")
                if entry.get("detail"):
                    ui.label(entry["detail"]).classes("text-xs text-grey-5")


# ── endpoints: ELN download and the processing notification ─────────────────

def _token_of(request: Request) -> str:
    return request.cookies.get("Authorization", "")


def _register_endpoints() -> None:
    """Two routes on the app's own FastAPI instance.

    They live under the same path prefix as the pages, so the existing reverse
    proxy entry covers them and the browser sends the NOMAD cookie along.
    """
    if getattr(nicegui_app, "_tga_endpoints", False):
        return
    nicegui_app._tga_endpoints = True

    @nicegui_app.get("/eln/{upload_id}")
    def download_eln(upload_id: str, request: Request):
        """The ELN package as a download, built from the entry's own data."""
        token = _token_of(request)
        if not token:
            return Response("sign in to NOMAD first", status_code=401)
        # Permission check through the API: only uploads this token may see are
        # read from disk (the staging volume has no per-user check of its own).
        status, response = _api["api"].api_json("GET", f"/uploads/{upload_id}", token)
        if status != 200:
            return Response("not allowed for this account", status_code=403)
        summary = entry_data.request_summary(upload_id)
        if not summary["fields"]:
            return Response("no processed data for this upload yet", status_code=404)
        window, delta = entry_data.dtg_settings(summary["fields"])
        settings = settings_mod.load_settings()
        code = str(upload_id)[:5]
        sample = summary["sample_name"] or str(
            (response.get("data") or {}).get("upload_name") or "")
        blob = eln_export.build_package(
            code=code, sample_name=sample, results=summary["results"],
            signals=summary["signals"],
            ctx={"entry_url": _gui_url(upload_id),
                 "requester": summary.get("requester", ""),
                 "operator": summary.get("operator", ""),
                 "measured_on": str(summary["fields"].get("last_processing_time") or "")[:10],
                 "exported_at": time.strftime("%Y-%m-%d %H:%M"),
                 "contacts": settings.get("recipients", {}).get("lab_contacts", {}),
                 "dtg_window": window, "dtg_delta": delta})
        filename = eln_export.package_filename(code, sample)
        return Response(blob, media_type="application/zip", headers={
            "Content-Disposition": f'attachment; filename="{filename}"'})

    @nicegui_app.post("/internal/notify/results-ready")
    async def notify_results_ready(request: Request):
        """Called by the NOMAD plugin when a measurement has been processed.

        Answers immediately and does the work in the background: the plugin must
        not wait for mails, and the entry archive is often still being written
        when the processing call returns.
        """
        if not INTERNAL_SECRET or request.headers.get("X-TGA-Secret", "") != INTERNAL_SECRET:
            return Response("forbidden", status_code=403)
        try:
            payload = await request.json()
        except Exception:                                       # noqa: BLE001
            payload = {}
        upload_id = str((payload or {}).get("upload_id") or "")
        if not upload_id:
            return Response("upload_id missing", status_code=400)
        asyncio.create_task(_notify_when_ready(upload_id, (payload or {}).get("error", "")))
        return Response("queued", status_code=202)


async def _notify_when_ready(upload_id: str, error: str, timeout: float = 120.0) -> None:
    """Wait for the entry archive, then send the notification.

    The archive appears a moment after processing; notifying before that would
    send a mail with empty results. A failure report is sent right away because
    there is nothing to wait for.
    """
    try:
        if error:
            events.notify("processing_failed_operator",
                          {"filename": f"upload {upload_id}", "error": error,
                           "upload_url": _gui_url(upload_id)})
            return
        deadline = time.time() + timeout
        summary: Dict[str, Any] = {}
        while time.time() < deadline:
            summary = entry_data.request_summary(upload_id)
            if summary.get("results"):
                break
            await asyncio.sleep(5)
        # Einmal reicht: NOMAD verarbeitet denselben Upload mehrfach (json, gz)
        # und jede Verarbeitung meldet sich. Der Fingerabdruck beschreibt deshalb
        # den INHALT der Ergebnisse, nicht den Zeitpunkt - sonst waere jeder
        # zweite Durchlauf eine neue Mail.
        fingerprint = _results_fingerprint(summary.get("results", {}))
        if settings_mod.was_notified(upload_id) == fingerprint:
            log.info("results for %s already notified, staying quiet", upload_id)
            return
        settings_mod.mark_notified(upload_id, fingerprint)
        row = {"upload_id": upload_id, "code": upload_id[:5],
               "sample": summary.get("sample_name", ""), "created": "",
               "gui_url": _gui_url(upload_id)}
        ctx = _export_context(row, summary)
        ctx["results"] = summary.get("results", {})
        for event in ("results_ready_user", "results_ready_operator"):
            events.notify(event, ctx)
    except Exception as error:                     # noqa: BLE001
        log.exception("results notification failed for %s", upload_id)
