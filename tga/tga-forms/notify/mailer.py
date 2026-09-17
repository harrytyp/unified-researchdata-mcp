"""Sending the notifications, with a queue for the time before mail is set up.

The lab has no mail account yet. The process should nevertheless be complete and
only need credentials later, so an attempt to send without a configured SMTP
account does not fail: the message is stored in the outbox and reported as
"queued". Once the account exists, ``flush_outbox()`` sends everything that piled
up - nothing is lost in the meantime.

Every attempt is written to the audit trail (subject, recipients, status - no
secrets, no message body) so it stays traceable who was notified about what.

SMTP defaults follow what the LRZ accepts (port 587 plus STARTTLS); a relay that
wants something else is configured in the admin page.
"""
from __future__ import annotations

import mimetypes
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from . import settings as settings_mod

MailResult = Tuple[str, str]          # (status, detail); status: sent/queued/failed


def _recipients(to: Any) -> List[str]:
    """Accept a string, a comma separated string or a list, return clean addresses."""
    if not to:
        return []
    if isinstance(to, str):
        parts: Iterable[str] = to.replace(";", ",").split(",")
    else:
        parts = to
    return [str(part).strip() for part in parts if str(part).strip()]


def is_configured(config: Optional[Dict[str, Any]] = None) -> Tuple[bool, str]:
    """Can mail be sent, and if not, why not?

    The reason is user facing text (it is shown in the admin page), so it names
    the missing field instead of just saying "not configured".
    """
    mail = (config or settings_mod.load_settings()).get("mail", {})
    if not mail.get("host"):
        return False, "no SMTP host configured"
    if not mail.get("from_address"):
        return False, "no sender address configured"
    return True, ""


def build_message(subject: str, body: str, to: Sequence[str], config: Dict[str, Any],
                  *, html: Optional[str] = None,
                  attachments: Optional[Sequence[Tuple[str, bytes]]] = None) -> EmailMessage:
    """Assemble the mail. Separate from sending so it can be tested without a server."""
    mail = config.get("mail", {})
    from_address = mail.get("from_address", "")
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = (f"{mail.get('from_name')} <{from_address}>"
                       if mail.get("from_name") else from_address)
    message["To"] = ", ".join(to)
    if mail.get("reply_to"):
        message["Reply-To"] = mail["reply_to"]
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid(domain=from_address.split("@")[-1] or None)
    message.set_content(body)
    if html:
        message.add_alternative(html, subtype="html")
    for filename, content in (attachments or []):
        guessed, _ = mimetypes.guess_type(filename)
        maintype, subtype = (guessed.split("/", 1) if guessed else ("application", "octet-stream"))
        message.add_attachment(content, maintype=maintype, subtype=subtype, filename=filename)
    return message


def send_mail(subject: str, body: str, to: Any, *, html: Optional[str] = None,
              attachments: Optional[Sequence[Tuple[str, bytes]]] = None,
              config: Optional[Dict[str, Any]] = None,
              event: str = "") -> MailResult:
    """Send one mail, or queue it when SMTP is not configured (yet).

    Never raises: a notification must not break the workflow it reports on.
    """
    config = config or settings_mod.load_settings()
    recipients = _recipients(to)
    if not recipients:
        return "failed", "no recipients"

    ready, reason = is_configured(config)
    if not ready:
        settings_mod.outbox_append({
            "event": event, "subject": subject, "to": recipients,
            "body": body, "reason": reason,
        })
        settings_mod.log_sent({"event": event, "subject": subject, "to": recipients,
                               "status": "queued", "detail": reason})
        return "queued", reason

    mail = config["mail"]
    try:
        message = build_message(subject, body, recipients, config,
                                html=html, attachments=attachments)
        context = ssl.create_default_context()
        with smtplib.SMTP(mail["host"], int(mail.get("port") or 587), timeout=25) as server:
            if mail.get("starttls", True):
                server.ehlo()
                server.starttls(context=context)
                server.ehlo()
            if mail.get("username"):
                # The password is read from the file, used here and never logged.
                server.login(mail["username"], mail.get("password") or "")
            server.send_message(message)
    except Exception as error:                     # noqa: BLE001 - report, never raise
        detail = f"{type(error).__name__}: {error}"
        settings_mod.log_sent({"event": event, "subject": subject, "to": recipients,
                               "status": "failed", "detail": detail})
        return "failed", detail

    settings_mod.log_sent({"event": event, "subject": subject, "to": recipients,
                           "status": "sent", "detail": ""})
    return "sent", ""


def flush_outbox(config: Optional[Dict[str, Any]] = None) -> Dict[str, int]:
    """Try to send everything queued so far.

    Failures stay in the outbox instead of being dropped - they are the whole
    reason the queue exists.
    """
    config = config or settings_mod.load_settings()
    ready, reason = is_configured(config)
    if not ready:
        return {"sent": 0, "kept": len(settings_mod.outbox_read()), "reason": reason}

    kept: List[Dict[str, Any]] = []
    sent = failed = 0
    for record in settings_mod.outbox_read():
        status, _detail = send_mail(record.get("subject", ""), record.get("body", ""),
                                    record.get("to", []), config=config,
                                    event=record.get("event", ""))
        if status == "sent":
            sent += 1
        else:
            failed += 1
            kept.append(record)
    settings_mod.outbox_replace(kept)
    return {"sent": sent, "kept": failed}


def outbox_clear() -> int:
    """Drop the queued notifications, return how many were thrown away.

    The mails are gone for good afterwards; the requests they talk about are not
    touched. Callers ask first (see the admin page).
    """
    count = len(settings_mod.outbox_read())
    settings_mod.outbox_replace([])
    return count


def outbox_summary() -> Dict[str, Any]:
    """Small overview for the admin page: how many are waiting, since when."""
    records = settings_mod.outbox_read()
    return {
        "count": len(records),
        "oldest": records[0].get("queued_at", "") if records else "",
        "events": sorted({r.get("event", "") for r in records}),
    }
