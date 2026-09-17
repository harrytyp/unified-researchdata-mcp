"""Which notification goes out for which state change.

The events are named after what happened, not after who receives them, and each
one is switched on or off in the settings - a lab that does not want a mail for
every processed measurement turns it off in the admin page instead of editing
code.

Two rules hold for all of them:

* A notification never breaks the workflow it reports on. Sending happens after
  the upload or the processing succeeded, every error is caught and returned.
* Recipients are decided here, not by the caller, so "the operators" means the
  same list everywhere and stays configurable in one place.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from . import mailer, settings as settings_mod, templates

log = logging.getLogger("tga.notify")

EVENTS = tuple(templates.BUILDERS)


def event_enabled(event: str, config: Optional[Dict[str, Any]] = None) -> bool:
    config = config or settings_mod.load_settings()
    return bool((config.get("notifications") or {}).get(event, True))


def requester_consent(ctx: Dict[str, Any]) -> bool:
    """Did the requester agree to be informed by email?

    The consent comes with the request (the form asks for it). Without it no
    mail goes to that address - writing to somebody who did not ask for it is
    exactly what the rule is for.
    """
    value = ctx.get("notify_requester")
    if value is None and isinstance(ctx.get("fields"), dict):
        value = (ctx["fields"] or {}).get("notify_requester")
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in ("1", "true", "yes", "on", "ja")


def recipients_for(event: str, ctx: Dict[str, Any],
                   config: Optional[Dict[str, Any]] = None) -> List[str]:
    """Who gets this event.

    The audience comes from the template registry, the addresses from the
    settings (operators) or from the request itself (the requester's address,
    which the form stores with the entry).
    """
    config = config or settings_mod.load_settings()
    audience = templates.DEFAULT_AUDIENCE.get(event, "operators")
    recipients: List[str] = []
    if audience in ("operators", "both"):
        recipients += [str(a).strip() for a in
                       (config.get("recipients", {}).get("operators") or []) if str(a).strip()]
    if audience in ("requester", "both"):
        # The requester's address is stored with the request; an operator address
        # configured as fallback keeps the notification from vanishing when a
        # request has no address (older requests, or a login without one).
        who = ctx.get("requester_email") or ctx.get("recipient")
        if who and requester_consent(ctx):
            recipients.append(str(who).strip())
        elif who:
            # Adresse bekannt, aber keine Zustimmung: sie wird nicht benutzt.
            log.info("no mail to the requester for %s: no consent (%s)",
                     event, ctx.get("code") or "?")
        elif audience == "requester":
            recipients += [str(a).strip() for a in
                           (config.get("recipients", {}).get("operators") or []) if str(a).strip()]
    # Keep the order, drop duplicates.
    seen = set()
    return [r for r in recipients if not (r in seen or seen.add(r))]


def notify(event: str, ctx: Dict[str, Any], *,
           config: Optional[Dict[str, Any]] = None,
           attachments: Optional[List] = None) -> Dict[str, Any]:
    """Render and send one event. Returns a small report, never raises.

    The report is what the admin page and the tests look at: which addresses,
    which status. It contains no message body and no secret.
    """
    if event not in templates.BUILDERS:
        return {"event": event, "status": "unknown-event", "recipients": [], "detail": ""}
    config = config or settings_mod.load_settings()
    if not event_enabled(event, config):
        return {"event": event, "status": "disabled", "recipients": [], "detail": ""}

    recipients = recipients_for(event, ctx, config)
    if not recipients:
        return {"event": event, "status": "no-recipients", "recipients": [], "detail": ""}

    try:
        subject, text, html = templates.BUILDERS[event](ctx)
    except Exception as error:                     # noqa: BLE001
        log.exception("template %s failed", event)
        return {"event": event, "status": "template-error", "recipients": recipients,
                "detail": f"{type(error).__name__}: {error}"}

    status, detail = mailer.send_mail(subject, text, recipients, html=html,
                                      attachments=attachments, config=config, event=event)
    return {"event": event, "status": status, "recipients": recipients,
            "detail": detail, "subject": subject}
